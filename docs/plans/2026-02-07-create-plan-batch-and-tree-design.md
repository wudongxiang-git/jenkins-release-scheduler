# 创建计划页：树样式优化 + 批量设置发版项目与分支

## 目标与约束

- **目标**：选 10 个后端 job → 一次设置发版项目 + 分支；再选 2 个前端 job → 一次设置；最终创建计划。兼顾单任务可调（灵活性）与批量统一设（便捷性）。
- **约束**：沿用现有 API；创建计划仍从树中收集各 job 的 `build_params`/分支等，不改变提交结构。

## 一、批量设置交互

- **触发**：当至少勾选 1 个任务时，在「选择要发版的任务」下方显示工具栏，含「批量设置」「全部展开」「全部收起」；取消全选时隐藏。
- **弹窗**：发版项目（GitLab 连接 + 项目，可选「不修改」）、分支（文本）、操作（可选）。应用至已选 N 个任务。
- **应用逻辑**：
  - 发版项目：调用 `POST /api/job-gitlab-override/batch` 一次写入多任务。
  - 分支/操作：已展开节点直接写 DOM；未展开节点存入 `pendingBatchMap`（path → { branch, operation, branchParam, opParam }），首次展开时从 map 填表并删除；提交时对未展开但存在于 map 的任务用 map 中的参数名与值组 params。

## 二、树节点样式

- 文件夹：浅底、左边距区分。
- 任务：勾选后左侧蓝色竖条 + 浅蓝底（`.job-selected`）。
- 全部展开/全部收起按钮。
- 任务参数区与树左边距对齐、轻分隔线。

## 三、实现要点

- **后端**：`app.py` 新增 `POST /api/job-gitlab-override/batch`，body: `job_paths`, `gitlab_config_id`, `gitlab_project_id`。
- **前端**：`index.html` 增加工具栏、批量弹窗、`pendingBatchMap`；job 勾选并渲染参数后调用 `applyPendingBatchToNode`；提交时对无表单的已选任务从 `pendingBatchMap` 取 branchParam/opParam 组 params。

## 验收

- 勾选多个任务 → 出现「批量设置」→ 弹窗设置发版项目 + 分支并应用 → 已展开任务立即更新，未展开任务在展开后带出批量值；创建计划提交后各任务参数与预期一致；单任务仍可手动覆盖。
