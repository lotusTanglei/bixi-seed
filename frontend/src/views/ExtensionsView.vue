<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";

import { api } from "../api/http";
import { useSessionStore } from "../stores/session";

interface Draft {
  id: number;
  key: string;
  name: string;
  description: string;
  files: Record<string, string>;
  dependencies: string[];
  permission_manifest: string[];
  validated_hash: string;
  enabled_hash: string;
  status: "draft" | "validated" | "rejected" | "enabled";
  static_checks: { passed?: boolean; dependency_check?: string; static_check?: string; permission_check?: string; errors?: string[]; installed_dependencies?: { name: string; version: string }[] };
}

const session = useSessionStore();
const drafts = ref<Draft[]>([]);
const selected = ref<Draft | null>(null);
const creating = ref(false);
const busy = ref(false);
const error = ref("");
const permissionOptions = computed(() => session.activeOrganization?.permissions ?? []);
function defaultForm() { return {
  key: "", name: "", description: "", dependencies: "", permission_manifest: [] as string[],
  files: JSON.stringify({ "extension.py": "def transform(value):\n    return value\n", "manifest.json": '{"version": 1}' }, null, 2),
}; }
const form = reactive(defaultForm());
const statusLabels = { draft: "草稿", validated: "静态校验通过", rejected: "校验未通过", enabled: "已确认收录（未执行）" };
let loadRevision = 0;
let contextRevision = 0;
let operationRevision = 0;

function currentContext() {
  return { organizationId: session.activeOrganizationId, revision: contextRevision };
}

function isCurrentContext(context: ReturnType<typeof currentContext>) {
  return context.organizationId === session.activeOrganizationId && context.revision === contextRevision;
}

function beginOperation() {
  const operation = { context: currentContext(), revision: ++operationRevision };
  busy.value = true;
  error.value = "";
  return operation;
}

function isCurrentOperation(operation: ReturnType<typeof beginOperation>) {
  return isCurrentContext(operation.context) && operation.revision === operationRevision;
}

async function load() {
  const revision = ++loadRevision;
  const context = currentContext();
  selected.value = null;
  error.value = "";
  drafts.value = [];
  try {
    const result = await api<Draft[]>("/extensions/drafts/");
    if (isCurrentContext(context) && revision === loadRevision) drafts.value = result;
  } catch (reason) {
    if (isCurrentContext(context) && revision === loadRevision) error.value = reason instanceof Error ? reason.message : "无法加载扩展草稿";
  }
}

async function create() {
  const operation = beginOperation();
  try {
    const files: unknown = JSON.parse(form.files);
    if (!files || typeof files !== "object" || Array.isArray(files)) throw new Error("文件清单必须是 JSON 对象");
    await api<Draft>("/extensions/drafts/", {
      method: "POST", body: { ...form, files, dependencies: form.dependencies.split("\n").map((item) => item.trim()).filter(Boolean) },
    });
    if (!isCurrentOperation(operation)) return;
    creating.value = false;
    await load();
    if (!isCurrentOperation(operation)) return;
    ElMessage.success("草稿已保存并完成静态检查，尚未收录或执行");
  } catch (reason) {
    if (isCurrentOperation(operation)) error.value = reason instanceof Error ? reason.message : "创建草稿失败";
  } finally {
    if (isCurrentOperation(operation)) busy.value = false;
  }
}

async function validate(draft: Draft) {
  const operation = beginOperation();
  try {
    const result = await api<Draft>(`/extensions/drafts/${draft.id}/validate/`, { method: "POST", body: {} });
    if (!isCurrentOperation(operation)) return;
    drafts.value = drafts.value.map((item) => item.id === result.id ? result : item);
    selected.value = result;
    ElMessage.success("依赖、代码和权限清单检查通过");
  } catch (reason) {
    if (!isCurrentOperation(operation)) return;
    await load();
    if (!isCurrentOperation(operation)) return;
    selected.value = drafts.value.find((item) => item.id === draft.id) ?? null;
    error.value = reason instanceof Error ? reason.message : "检查未通过";
  } finally {
    if (isCurrentOperation(operation)) busy.value = false;
  }
}

async function enable(draft: Draft) {
  const context = currentContext();
  try {
    await ElMessageBox.confirm(`确认将“${draft.name}”收录到当前组织的受控目录？权限清单：${draft.permission_manifest.join("、") || "无"}。此操作不会加载或执行草稿代码。`, "确认收录扩展", { confirmButtonText: "确认收录（不执行）", cancelButtonText: "取消", type: "warning" });
  } catch {
    return;
  }
  if (!isCurrentContext(context)) return;
  const operation = beginOperation();
  try {
    const result = await api<Draft>(`/extensions/drafts/${draft.id}/enable/`, { method: "POST", body: { confirmed: true, content_hash: draft.validated_hash } });
    if (!isCurrentOperation(operation)) return;
    drafts.value = drafts.value.map((item) => item.id === result.id ? result : item);
    selected.value = result;
    ElMessage.success("已收录到受控目录，代码未加载或执行");
  } catch (reason) {
    if (!isCurrentOperation(operation)) return;
    await load();
    if (!isCurrentOperation(operation)) return;
    error.value = reason instanceof Error ? reason.message : "收录失败，请重新检查草稿";
  } finally {
    if (isCurrentOperation(operation)) busy.value = false;
  }
}

watch(() => session.activeOrganizationId, () => {
  contextRevision += 1;
  operationRevision += 1;
  busy.value = false;
  creating.value = false;
  selected.value = null;
  drafts.value = [];
  Object.assign(form, defaultForm());
  void load();
}, { immediate: true });
</script>

<template>
  <div class="page-heading">
    <div><h1>扩展草稿目录</h1><p>检查文件、依赖和权限后，由你确认收录。</p></div>
    <el-button type="primary" :disabled="busy" @click="creating = true">新建草稿</el-button>
  </div>
  <el-alert title="当前只管理受控目录。收录不会加载、执行代码或授予权限；静态检查不代表运行时安全隔离。" type="info" :closable="false" show-icon />
  <el-alert v-if="error" :title="error" type="error" :closable="false" class="surface-section" />
  <section class="surface-section">
    <el-table :data="drafts" empty-text="当前组织没有扩展草稿" @row-click="(row: Draft) => selected = row">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="key" label="编码" />
      <el-table-column label="状态"><template #default="{ row }">{{ statusLabels[row.status as Draft['status']] }}</template></el-table-column>
      <el-table-column label="操作" width="230"><template #default="{ row }">
        <el-button link @click.stop="selected = row">预览</el-button>
        <el-button link :disabled="busy || row.status === 'enabled'" @click.stop="validate(row)">重新检查</el-button>
        <el-button link type="primary" :disabled="busy || row.status !== 'validated' || !row.validated_hash" @click.stop="selected = row">准备收录</el-button>
      </template></el-table-column>
    </el-table>
  </section>
  <section v-if="selected" class="surface-section">
    <h2>{{ selected.name }} · {{ statusLabels[selected.status] }}</h2>
    <p>{{ selected.description }}</p>
    <p>权限清单：{{ selected.permission_manifest.join('、') || '无' }}</p>
    <p>依赖：{{ selected.dependencies.join('、') || '无' }}</p>
    <p>检查：依赖 {{ selected.static_checks.dependency_check || '未检查' }} / 代码 {{ selected.static_checks.static_check || '未检查' }} / 权限 {{ selected.static_checks.permission_check || '未检查' }}</p>
    <p v-for="item in selected.static_checks.installed_dependencies || []" :key="item.name">{{ item.name }}：已安装 {{ item.version }}</p>
    <p>内容校验值：<code>{{ selected.validated_hash || '校验未通过或需重新检查' }}</code></p>
    <el-alert v-for="(item, index) in selected.static_checks.errors || []" :key="index" :title="item" type="error" :closable="false" />
    <el-collapse><el-collapse-item v-for="(content, path) in selected.files" :key="path" :title="path"><pre style="white-space: pre-wrap; overflow-wrap: anywhere">{{ content }}</pre></el-collapse-item></el-collapse>
    <el-button v-if="selected.status === 'validated' && selected.validated_hash" type="primary" :loading="busy" @click="enable(selected)">确认收录（不执行代码）</el-button>
  </section>
  <el-dialog v-model="creating" title="新建受控扩展草稿" width="720px">
    <el-form label-position="top">
      <el-form-item label="编码"><el-input v-model="form.key" maxlength="100" placeholder="customer-extension" /></el-form-item>
      <el-form-item label="名称"><el-input v-model="form.name" maxlength="160" /></el-form-item>
      <el-form-item label="说明"><el-input v-model="form.description" maxlength="500" /></el-form-item>
      <el-form-item label="文件清单 JSON（相对路径 → 文本内容，仅 Python / JSON / Markdown / TXT）"><el-input v-model="form.files" type="textarea" :rows="9" /></el-form-item>
      <el-form-item label="依赖要求（每行一项，只接受已安装包及版本约束，不会安装依赖）"><el-input v-model="form.dependencies" type="textarea" :rows="2" placeholder="packaging>=24,<27" /></el-form-item>
      <el-form-item label="权限清单（仅当前组织已持有权限；记录清单，不授予权限）"><el-select v-model="form.permission_manifest" multiple class="full-width"><el-option v-for="code in permissionOptions" :key="code" :label="code" :value="code" /></el-select></el-form-item>
    </el-form>
    <template #footer><el-button @click="creating = false">取消</el-button><el-button type="primary" :loading="busy" @click="create">保存并检查</el-button></template>
  </el-dialog>
</template>
