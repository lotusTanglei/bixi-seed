<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage, ElMessageBox } from "element-plus";
import { ArrowLeft, Delete, Edit, Plus, Refresh, View as ViewIcon } from "@element-plus/icons-vue";

import { api } from "../api/http";

type FieldType = "text" | "number" | "date" | "enum" | "boolean";

interface FeatureField {
  key: string;
  label: string;
  type: FieldType;
  required?: boolean;
  options?: string[];
}

interface Feature {
  id: string;
  key: string;
  name: string;
  description: string;
  status: string;
  current_version: number;
  manifest: {
    fields: FeatureField[];
    list?: { columns?: string[]; search_fields?: string[] };
    form?: { fields?: string[] };
    detail?: { fields?: string[] };
    actions?: { create?: boolean; read?: boolean; update?: boolean; delete?: boolean };
  };
}

interface FeatureVersion {
  id: number;
  version: number;
  name: string;
  description: string;
  manifest: Feature["manifest"];
  created_by: number | null;
  created_at: string;
  note: string;
}

interface RecordItem {
  id: string;
  data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

interface RecordResponse {
  items: RecordItem[];
  pagination: { page: number; page_size: number; total: number };
  feature: Feature;
}

const route = useRoute();
const router = useRouter();
const feature = ref<Feature | null>(null);
const records = ref<RecordItem[]>([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const search = ref("");
const sort = ref("-updated_at");
const loading = ref(true);
const dialog = ref(false);
const saving = ref(false);
const editingId = ref<string | null>(null);
const detailDialog = ref(false);
const recordDetail = ref<RecordItem | null>(null);
const versions = ref<FeatureVersion[]>([]);
const versionDialog = ref(false);
const selectedVersion = ref<FeatureVersion | null>(null);
const formData = reactive<Record<string, unknown>>({});

const versionDiff = computed(() => {
  if (!feature.value || !selectedVersion.value) return [];
  const current = new Map(feature.value.manifest.fields.map((field) => [field.key, field]));
  const previous = new Map(selectedVersion.value.manifest.fields.map((field) => [field.key, field]));
  const keys = [...new Set([...current.keys(), ...previous.keys()])];
  return keys.map((key) => ({
    key,
    before: previous.get(key)?.label ?? "已移除",
    after: current.get(key)?.label ?? "已移除",
    changed: JSON.stringify(previous.get(key)) !== JSON.stringify(current.get(key)),
  })).filter((item) => item.changed);
});

const columns = computed(() => {
  if (!feature.value) return [];
  const configured = feature.value.manifest.list?.columns;
  return configured?.length
    ? feature.value.manifest.fields.filter((field) => configured.includes(field.key))
    : feature.value.manifest.fields;
});

const formFields = computed(() => {
  if (!feature.value) return [];
  const configured = feature.value.manifest.form?.fields;
  return configured?.length
    ? feature.value.manifest.fields.filter((field) => configured.includes(field.key))
    : feature.value.manifest.fields;
});

const detailFields = computed(() => {
  if (!feature.value) return [];
  const configured = feature.value.manifest.detail?.fields;
  return configured?.length
    ? feature.value.manifest.fields.filter((field) => configured.includes(field.key))
    : feature.value.manifest.fields;
});

const sortOptions = computed(() => [
  { label: "更新时间（新到旧）", value: "-updated_at" },
  { label: "更新时间（旧到新）", value: "updated_at" },
  { label: "创建时间（新到旧）", value: "-created_at" },
  ...(feature.value?.manifest.fields ?? []).flatMap((field) => [
    { label: `${field.label}（升序）`, value: field.key },
    { label: `${field.label}（降序）`, value: `-${field.key}` },
  ]),
]);

function featureUrl() {
  return `${featureBaseUrl()}records/`;
}

function featureBaseUrl() {
  return `/features/${String(route.params.featureId)}/`;
}

async function load() {
  loading.value = true;
  try {
    const result = await api<RecordResponse>(
      `${featureUrl()}?page=${page.value}&page_size=${pageSize.value}&q=${encodeURIComponent(search.value)}&sort=${encodeURIComponent(sort.value)}`,
    );
    feature.value = result.feature;
    records.value = result.items;
    total.value = result.pagination.total;
    versions.value = await api<FeatureVersion[]>(`${featureBaseUrl()}versions/`).catch(() => []);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "无法加载功能数据");
  } finally {
    loading.value = false;
  }
}

async function openVersion(version: FeatureVersion) {
  selectedVersion.value = await api<FeatureVersion>(`${featureBaseUrl()}versions/${version.version}/`);
  versionDialog.value = true;
}

async function rollback(version: FeatureVersion) {
  try {
    await ElMessageBox.confirm(`确定回滚到版本 ${version.version}？当前定义会生成新的版本快照。`, "回滚功能", { type: "warning" });
    await api(`${featureBaseUrl()}rollback/`, { method: "POST", body: { version: version.version, confirm: true } });
    ElMessage.success("功能已回滚并重新发布");
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error instanceof Error ? error.message : "回滚失败");
  }
}

function resetForm(data: Record<string, unknown> = {}) {
  Object.keys(formData).forEach((key) => delete formData[key]);
  feature.value?.manifest.fields.forEach((field) => {
    formData[field.key] = data[field.key] ?? (field.type === "boolean" ? false : "");
  });
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialog.value = true;
}

function openEdit(record: RecordItem) {
  editingId.value = record.id;
  resetForm(record.data);
  dialog.value = true;
}

async function openDetail(record: RecordItem) {
  try {
    recordDetail.value = await api<RecordItem>(`${featureUrl()}${record.id}/`);
    detailDialog.value = true;
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "无法加载数据详情");
  }
}

async function save() {
  saving.value = true;
  try {
    const path = editingId.value ? `${featureUrl()}${editingId.value}/` : featureUrl();
    await api(path, { method: editingId.value ? "PATCH" : "POST", body: { data: { ...formData } } });
    dialog.value = false;
    ElMessage.success(editingId.value ? "数据已更新" : "数据已创建");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存数据失败");
  } finally {
    saving.value = false;
  }
}

async function remove(record: RecordItem) {
  try {
    await ElMessageBox.confirm("删除后不能恢复，确定继续吗？", "删除数据", { type: "warning" });
    await api(`${featureUrl()}${record.id}/`, { method: "DELETE" });
    ElMessage.success("数据已删除");
    if (records.value.length === 1 && page.value > 1) page.value -= 1;
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close") {
      ElMessage.error(error instanceof Error ? error.message : "删除数据失败");
    }
  }
}

function displayValue(value: unknown, field: FeatureField) {
  if (value === null || value === undefined || value === "") return "-";
  if (field.type === "boolean") return value ? "是" : "否";
  return String(value);
}

function setField(key: string, value: unknown) {
  formData[key] = value;
}

onMounted(load);
</script>

<template>
  <div class="page-header">
    <div>
      <el-button link :icon="ArrowLeft" @click="router.push({ name: 'dashboard' })">返回工作台</el-button>
      <div class="eyebrow feature-eyebrow">FEATURE / {{ feature?.key }}</div>
      <h1>{{ feature?.name ?? "业务功能" }}</h1>
      <p>{{ feature?.description || "暂无功能说明" }}</p>
    </div>
    <div class="page-actions">
      <el-button :icon="Refresh" circle title="刷新" aria-label="刷新" @click="load" />
      <el-button v-if="versions.length" :icon="ViewIcon" @click="openVersion(versions[0])">版本 {{ feature?.current_version ?? 0 }}</el-button>
      <el-button v-if="feature?.manifest.actions?.create !== false" type="primary" :icon="Plus" @click="openCreate">新增数据</el-button>
    </div>
  </div>

  <section v-if="versions.length" class="surface-section feature-version-section">
    <div class="section-heading"><div><h2>版本历史</h2><p>当前版本 {{ feature?.current_version ?? 0 }}，历史快照不可变。</p></div></div>
    <el-table :data="versions" size="small">
      <el-table-column prop="version" label="版本" width="90" />
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="created_at" label="发布时间" width="190" />
      <el-table-column label="操作" width="180">
        <template #default="{ row }"><el-button link @click="openVersion(row)">查看 diff</el-button><el-button v-if="row.version !== feature?.current_version" link type="warning" @click="rollback(row)">回滚</el-button></template>
      </el-table-column>
    </el-table>
  </section>

  <section class="surface-section" v-loading="loading">
    <div class="section-heading feature-toolbar">
      <div>
        <h2>数据列表</h2>
        <p>共 {{ total }} 条数据</p>
      </div>
      <div class="feature-filters">
        <el-input v-model="search" clearable placeholder="搜索数据" class="feature-search" @keyup.enter="page = 1; load()" @clear="page = 1; load()" />
        <el-select v-model="sort" class="feature-sort" @change="page = 1; load()">
          <el-option v-for="option in sortOptions" :key="option.value" :label="option.label" :value="option.value" />
        </el-select>
      </div>
    </div>
    <el-table :data="records" size="small" empty-text="暂无数据">
      <el-table-column v-for="field in columns" :key="field.key" :label="field.label" min-width="140">
        <template #default="{ row }">{{ displayValue(row.data[field.key], field) }}</template>
      </el-table-column>
      <el-table-column label="更新时间" width="180">
        <template #default="{ row }">{{ row.updated_at }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link :icon="ViewIcon" title="查看详情" aria-label="查看详情" @click="openDetail(row)" />
          <el-button v-if="feature?.manifest.actions?.update !== false" link :icon="Edit" title="编辑" aria-label="编辑" @click="openEdit(row)" />
          <el-button v-if="feature?.manifest.actions?.delete !== false" link type="danger" :icon="Delete" title="删除" aria-label="删除" @click="remove(row)" />
        </template>
      </el-table-column>
    </el-table>
    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      class="feature-pagination"
      layout="total, prev, pager, next"
      :total="total"
      @current-change="load"
      @size-change="page = 1; load()"
    />
  </section>

  <el-dialog v-model="detailDialog" :title="`${feature?.name ?? '数据'}详情`" width="560px">
    <div v-if="recordDetail && feature" class="detail-grid">
      <div v-for="field in detailFields" :key="field.key" class="detail-item">
        <span>{{ field.label }}</span>
        <strong>{{ displayValue(recordDetail.data[field.key], field) }}</strong>
      </div>
      <div class="detail-item">
        <span>更新时间</span>
        <strong>{{ recordDetail.updated_at }}</strong>
      </div>
    </div>
  </el-dialog>

  <el-dialog v-model="versionDialog" :title="`版本 ${selectedVersion?.version ?? ''}`" width="620px">
    <el-table :data="versionDiff" size="small" empty-text="与当前版本没有字段变化">
      <el-table-column prop="key" label="字段" width="160" />
      <el-table-column prop="before" label="历史版本" />
      <el-table-column prop="after" label="当前版本" />
    </el-table>
    <p v-if="selectedVersion?.note" class="form-hint">{{ selectedVersion.note }}</p>
  </el-dialog>

  <el-dialog v-model="dialog" :title="editingId ? '编辑数据' : '新增数据'" width="560px">
    <el-form v-if="feature" label-position="top">
      <el-form-item v-for="field in formFields" :key="field.key" :label="field.label" :required="field.required">
        <el-input v-if="field.type === 'text'" :model-value="formData[field.key] as string" @update:model-value="setField(field.key, $event)" />
        <el-input-number v-else-if="field.type === 'number'" :model-value="formData[field.key] as number" controls-position="right" class="full-width" @update:model-value="setField(field.key, $event)" />
        <el-date-picker v-else-if="field.type === 'date'" :model-value="formData[field.key] as string" type="date" value-format="YYYY-MM-DD" class="full-width" @update:model-value="setField(field.key, $event)" />
        <el-select v-else-if="field.type === 'enum'" :model-value="formData[field.key] as string" class="full-width" @update:model-value="setField(field.key, $event)">
          <el-option v-for="option in field.options ?? []" :key="option" :label="option" :value="option" />
        </el-select>
        <el-switch v-else :model-value="Boolean(formData[field.key])" @update:model-value="setField(field.key, $event)" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-dialog>
</template>
