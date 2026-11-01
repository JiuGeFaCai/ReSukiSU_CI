#!/usr/bin/env bash
set -euo pipefail

: "${TARGET_REPO:?}" "${TARGET_BRANCH:?}" "${TARGET_WORKFLOW_ID:?}"
: "${N_LATEST_RUNS:?}" "${GITHUB_REPOSITORY:?}"
: "${SYNC_NAME:?}" "${TAG_PREFIX:?}" "${ARTIFACT_NAME:?}" "${APK_PREFIX:?}"

checked=0
published=0
repaired=0
existing=0
skipped=0
sync_tmp=$(mktemp -d)

finish() {
    local sync_exit=$?
    local result=success
    if (( sync_exit != 0 )); then
        result=failure
        echo "::error::$SYNC_NAME sync failed. See the error above; the next run will retry."
    fi
    {
        printf '### %s sync: %s\n\n' "$SYNC_NAME" "$result"
        printf '| Checked | Published | Repaired | Already published | Upstream failed/skipped |\n'
        printf '| --- | --- | --- | --- | --- |\n'
        printf '| %s | %s | %s | %s | %s |\n' "$checked" "$published" "$repaired" "$existing" "$skipped"
    } > "$sync_tmp/summary.md"
    cat "$sync_tmp/summary.md"
    if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
        cat "$sync_tmp/summary.md" >> "$GITHUB_STEP_SUMMARY"
    fi
    rm -rf -- "$sync_tmp"
}
trap finish EXIT

fail() {
    printf '::error::%s\n' "$*" >&2
    exit 1
}

# 只有 HTTP 404 表示 Release 不存在；鉴权、限流等错误必须终止同步。
# --include 提供状态行，避免把 gh 的所有非零退出码都当成“尚未发布”。
get_release() {
    local http_version='' http_status='' _http_reason=''
    local draft_response draft_id
    release_exists=false
    release_json='{}'
    if gh api --include "repos/$GITHUB_REPOSITORY/releases/tags/$tag_name" \
        > "$sync_tmp/release-response" 2> "$sync_tmp/release-error"; then
        release_json=$(sed '1,/^[[:space:]]*$/d' "$sync_tmp/release-response")
        release_exists=true
    else
        read -r http_version http_status _http_reason < "$sync_tmp/release-response" || true
        if [[ "$http_version" != HTTP/* || "$http_status" != 404 ]]; then
            cat "$sync_tmp/release-error" >&2
            fail "Cannot check release $tag_name."
        fi
        # REST 的 tag 接口查不到待发布的草稿；上传中断可能留下这种草稿。
        # GraphQL 变量由 gh 传参，不在 Shell 中展开。
        # shellcheck disable=SC2016
        draft_response=$(gh api graphql -f query='
            query($owner: String!, $name: String!, $tag: String!) {
                repository(owner: $owner, name: $name) {
                    release(tagName: $tag) { databaseId }
                }
            }' -f owner="${GITHUB_REPOSITORY%/*}" -f name="${GITHUB_REPOSITORY##*/}" -f tag="$tag_name")
        draft_id=$(jq -r '.data.repository |
            if type != "object" then error("Repository unavailable in release lookup")
            else .release.databaseId // empty end' <<< "$draft_response")
        if [[ -n "$draft_id" ]]; then
            [[ "$draft_id" =~ ^[0-9]+$ ]] || fail "Invalid release id for $tag_name."
            release_json=$(gh api "repos/$GITHUB_REPOSITORY/releases/$draft_id")
            release_exists=true
        fi
    fi
    if [[ "$release_exists" == true ]]; then
        jq -e --arg tag "$tag_name" \
            '.tag_name == $tag and (.assets | type == "array") and (.draft | type == "boolean")' \
            <<< "$release_json" > /dev/null
    fi
}

echo "Checking latest $N_LATEST_RUNS runs of $TARGET_REPO (workflow $TARGET_WORKFLOW_ID, branch $TARGET_BRANCH)..."
runs_response=$(gh api "repos/$TARGET_REPO/actions/workflows/$TARGET_WORKFLOW_ID/runs?branch=$TARGET_BRANCH&per_page=$N_LATEST_RUNS")
runs_json=$(jq -c '[.workflow_runs[] |
    select(.event != "pull_request" and .event != "pull_request_target" and .status == "completed")] |
    reverse | .[] | {id, url: .html_url, sha: .head_sha, conclusion,
    msg: ((.head_commit.message // "") | split("\n")[0])}' <<< "$runs_response")

if [[ -z "$runs_json" ]]; then
    echo "No completed non-PR builds to sync."
    exit 0
fi

# here-string 保留计数；API 调用先完整结束，避免 pipefail + head 的 SIGPIPE。
while IFS= read -r run; do
    run_id=$(jq -r '.id' <<< "$run")
    run_url=$(jq -r '.url' <<< "$run")
    run_sha=$(jq -r '.sha' <<< "$run")
    run_msg=$(jq -r '.msg' <<< "$run")
    run_conclusion=$(jq -r '.conclusion' <<< "$run")
    tag_name="${TAG_PREFIX}_${run_id}"
    checked=$((checked + 1))
    echo "Checking run $run_id: $run_url"

    get_release
    if [[ "$release_exists" == true ]] && jq -e \
        --arg pattern "^${APK_PREFIX}.*_.*-release\\.apk$" '
        (.draft | not) and any(.assets[];
            .state == "uploaded" and .size > 0 and
            (.name | test($pattern)))
        ' <<< "$release_json" > /dev/null; then
        existing=$((existing + 1))
        echo "Release $tag_name already contains an uploaded APK. Skipping."
        continue
    fi
    repair_release=$release_exists
    release_is_draft=$(jq -r '.draft // false' <<< "$release_json")

    # 只同步配置的完整管理器产物，其他变体不能代替。
    # 必须取完所有页：上游一次构建有约 40 个产物。
    artifacts_response=$(gh api --paginate "repos/$TARGET_REPO/actions/runs/$run_id/artifacts?per_page=100")
    artifact_ids=$(jq -r --arg name "$ARTIFACT_NAME" \
        '.artifacts[] | select(.name == $name and (.expired | not)) | .id' \
        <<< "$artifacts_response")
    art_id=${artifact_ids%%$'\n'*}
    if [[ -z "$art_id" ]]; then
        if [[ "$run_conclusion" == success ]]; then
            fail "Successful upstream run $run_id has no unexpired $ARTIFACT_NAME artifact."
        fi
        skipped=$((skipped + 1))
        echo "::warning::Upstream run $run_id concluded $run_conclusion without a manager artifact. Skipping."
        continue
    fi

    run_dir="$sync_tmp/$run_id"
    mkdir -p "$run_dir"
    gh api "repos/$TARGET_REPO/actions/artifacts/$art_id/zip" > "$run_dir/manager.zip"
    unzip -q -o "$run_dir/manager.zip" -d "$run_dir"
    find "$run_dir" -type f -name "${APK_PREFIX}*_*-release.apk" -size +0c -print0 > "$sync_tmp/apks"
    mapfile -d '' -t apk_files < "$sync_tmp/apks"
    if (( ${#apk_files[@]} != 1 )); then
        fail "Expected one non-empty $SYNC_NAME release APK in run $run_id; found ${#apk_files[@]}."
    fi
    apk_file=${apk_files[0]}
    apk_size=$(stat -c '%s' "$apk_file")
    release_title=$(basename "$apk_file" .apk | sed -E "s/^${APK_PREFIX}_v/${SYNC_NAME} v/; s/-release$//")
    printf '从 %s 的 Build Manager CI 构建自动同步（%s 完整版管理器 APK）。\n\n- 上游 run：%s\n- commit：%s\n- 提交信息：%s\n' \
        "$TARGET_REPO" "$ARTIFACT_NAME" "$run_url" "$run_sha" "$run_msg" > "$sync_tmp/notes.md"

    if [[ "$repair_release" == true ]]; then
        echo "Repairing incomplete release $tag_name..."
        gh release upload "$tag_name" "$apk_file" --repo "$GITHUB_REPOSITORY" --clobber
        if [[ "$release_is_draft" == true ]]; then
            gh release edit "$tag_name" --repo "$GITHUB_REPOSITORY" --draft=false --latest=false
        fi
    else
        echo "Publishing $release_title (tag: $tag_name)..."
        gh release create "$tag_name" "$apk_file" --repo "$GITHUB_REPOSITORY" \
            --title "$release_title" --notes-file "$sync_tmp/notes.md" --latest=false
    fi

    # 发布命令成功后再确认附件，下一次可继续修复中断的上传。
    get_release
    if [[ "$release_exists" != true ]] || ! jq -e \
        --arg name "${apk_file##*/}" --argjson size "$apk_size" '
        (.draft | not) and any(.assets[];
            .name == $name and .size == $size and .state == "uploaded")
        ' <<< "$release_json" > /dev/null; then
        fail "Release $tag_name is missing the uploaded APK or its size does not match."
    fi
    if [[ "$repair_release" == true ]]; then
        repaired=$((repaired + 1))
    else
        published=$((published + 1))
    fi
done <<< "$runs_json"
