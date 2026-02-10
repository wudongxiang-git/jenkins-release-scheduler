"""
文件夹级「代码仓库类型」配置
按文件夹标识使用哪种代码仓库（GitLab / 云效 等），用于确定构建参数名，便于扩展而非依赖参数推断。
"""
# 供前端下拉展示：id 存库，label 展示；后续扩展在此追加即可
REPO_TYPES = [
    {"id": "gitlab", "label": "GitLab"},
    # 后续可加: {"id": "yunxiao", "label": "云效"},
]

# 各类型对应的 Jenkins 参数名（branch / operation / pod）
REPO_TYPE_PARAMS = {
    "gitlab": {
        "branch": "BRANCH_TAG",
        "operation": "请选择操作",
        "pod": "pod_num",
    },
    # 后续可加:
    # "yunxiao": {"branch": "GIT_BRANCH", "operation": "操作", "pod": "pod_num"},
}


def get_param_names_for_repo_type(repo_type):
    """根据仓库类型返回参数名映射，未配置或未知类型返回 None（由调用方做参数推断）。"""
    if not repo_type or repo_type not in REPO_TYPE_PARAMS:
        return None
    return REPO_TYPE_PARAMS[repo_type].copy()
