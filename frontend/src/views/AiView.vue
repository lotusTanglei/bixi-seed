<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";

import { api, apiStream } from "../api/http";
import { useSessionStore } from "../stores/session";

const DEEPSEEK_BASE_URL = "https://api.deepseek.com";
const DEEPSEEK_MODEL = "deepseek-v4-flash";

interface AiConfig {
  provider: string;
  base_url: string;
  model: string;
  is_enabled: boolean;
  has_api_key: boolean;
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface FeatureProposal {
  id: number;
  key: string;
  name: string;
  description: string;
  manifest: { fields: Array<{ key: string; label: string; type: string; required?: boolean }> };
  status: "proposed" | "created" | "rejected";
  feature_id: string | null;
}

type PromptTemplateKind = "custom" | "ledger" | "dashboard" | "form" | "workflow";

interface PromptTemplate {
  key: string;
  label: string;
  kind: PromptTemplateKind;
  description: string;
  business_label: string;
  object_label: string;
  fields_label: string;
  business_placeholder: string;
  object_placeholder: string;
  fields_placeholder: string;
  optional_label: string;
  optional_placeholder: string;
  business_name: string;
  object_name: string;
  fields: string;
  statuses: string;
  notes: string;
}

const config = reactive<AiConfig>({
  provider: "openai-compatible",
  base_url: DEEPSEEK_BASE_URL,
  model: DEEPSEEK_MODEL,
  is_enabled: true,
  has_api_key: false,
});
const apiKey = ref("");
const advancedConfigOpen = ref<string[]>([]);
const saving = ref(false);
const sending = ref(false);
const content = ref("");
const conversationId = ref<number | null>(null);
const messages = ref<ChatMessage[]>([]);
const proposal = ref<FeatureProposal | null>(null);
const planning = ref(false);
const confirming = ref(false);
const session = useSessionStore();
const canConfigureAi = computed(() => session.hasPermission("ai.configure"));
const canUseAi = computed(() => session.hasPermission("ai.use"));
const canManageFeatures = computed(() => session.hasPermission("feature.manage"));
const promptTemplates: PromptTemplate[] = [
  {
    key: "custom",
    label: "自定义功能",
    kind: "custom",
    description: "不限定类型，直接描述你想做的功能",
    business_label: "业务名称",
    object_label: "管理对象",
    fields_label: "核心字段",
    business_placeholder: "例如：客户管理",
    object_placeholder: "例如：客户",
    fields_placeholder: "例如：名称、负责人、日期",
    optional_label: "状态选项",
    optional_placeholder: "例如：待处理、处理中、已完成",
    business_name: "",
    object_name: "",
    fields: "",
    statuses: "",
    notes: "",
  },
  {
    key: "ledger",
    label: "台账类",
    kind: "ledger",
    description: "记录一类对象，提供查询、维护和明细查看",
    business_label: "台账名称",
    object_label: "管理对象",
    fields_label: "记录字段",
    business_placeholder: "例如：客户台账",
    object_placeholder: "例如：客户",
    fields_placeholder: "例如：名称、编号、负责人、备注",
    optional_label: "状态选项",
    optional_placeholder: "例如：待处理、处理中、已完成",
    business_name: "客户台账",
    object_name: "客户",
    fields: "客户名称、联系人、手机号、负责人、备注",
    statuses: "",
    notes: "",
  },
  {
    key: "dashboard",
    label: "图表类",
    kind: "dashboard",
    description: "围绕指标和维度，生成数据看板或统计页面",
    business_label: "看板名称",
    object_label: "数据主题",
    fields_label: "指标与维度",
    business_placeholder: "例如：销售看板",
    object_placeholder: "例如：销售数据",
    fields_placeholder: "例如：销售额、订单数、月份、部门",
    optional_label: "筛选条件",
    optional_placeholder: "例如：时间范围、部门、负责人",
    business_name: "经营看板",
    object_name: "销售数据",
    fields: "销售额、订单数、客户数、月份",
    statuses: "",
    notes: "",
  },
  {
    key: "form",
    label: "表单类",
    kind: "form",
    description: "收集和维护一类信息，适合登记、申请和信息采集",
    business_label: "表单名称",
    object_label: "收集对象",
    fields_label: "填写字段",
    business_placeholder: "例如：信息登记",
    object_placeholder: "例如：登记事项",
    fields_placeholder: "例如：姓名、联系方式、日期、说明",
    optional_label: "校验或选项",
    optional_placeholder: "例如：单选项、必填规则、手机号校验",
    business_name: "信息登记",
    object_name: "登记事项",
    fields: "姓名、联系方式、日期、说明",
    statuses: "",
    notes: "",
  },
  {
    key: "workflow",
    label: "流程类",
    kind: "workflow",
    description: "有处理人和状态流转，适合审批、工单和任务流程",
    business_label: "流程名称",
    object_label: "流程对象",
    fields_label: "业务字段",
    business_placeholder: "例如：请假审批",
    object_placeholder: "例如：请假申请",
    fields_placeholder: "例如：申请人、时间、事由、附件",
    optional_label: "流程状态",
    optional_placeholder: "例如：待处理、处理中、已完成",
    business_name: "请假审批",
    object_name: "请假申请",
    fields: "申请人、请假类型、开始时间、结束时间、事由",
    statuses: "",
    notes: "",
  },
];
const selectedTemplate = ref("custom");
const workspaceMode = ref("planner");
const optionalPlannerOpen = ref<string[]>([]);
const plannerForm = reactive({
  business_name: "",
  object_name: "",
  fields: "",
  statuses: "",
  notes: "",
});
const selectedTemplateDefinition = computed(
  () => promptTemplates.find((template) => template.key === selectedTemplate.value) ?? promptTemplates[0],
);
const activeWorkspaceMode = computed({
  get: () => (canManageFeatures.value ? workspaceMode.value : "chat"),
  set: (value: string) => {
    workspaceMode.value = value;
  },
});
function templateSentence(template: PromptTemplate, businessName: string, objectName: string, fields: string) {
  if (template.kind === "dashboard") {
    return `请帮我创建一个“${businessName}”图表功能，围绕“${objectName}”展示数据，关注指标和维度：${fields}。`;
  }
  if (template.kind === "form") {
    return `请帮我创建一个“${businessName}”表单功能，用于收集“${objectName}”信息，需要填写：${fields}。`;
  }
  if (template.kind === "workflow") {
    return `请帮我创建一个“${businessName}”流程功能，用于处理“${objectName}”，需要记录：${fields}。`;
  }
  if (template.kind === "ledger") {
    return `请帮我创建一个“${businessName}”台账功能，用于管理“${objectName}”，需要记录：${fields}。`;
  }
  return `请帮我创建一个“${businessName}”功能，用于管理“${objectName}”，需要记录：${fields}。`;
}
const promptTemplatePreview = computed(() => {
  const template = selectedTemplateDefinition.value;
  const businessName = plannerForm.business_name.trim() || template.business_label;
  const objectName = plannerForm.object_name.trim() || template.object_label;
  const fields = plannerForm.fields.trim() || template.fields_label;
  return templateSentence(template, businessName, objectName, fields);
});
const generatedPrompt = computed(() => {
  const template = selectedTemplateDefinition.value;
  const businessName = plannerForm.business_name.trim();
  const objectName = plannerForm.object_name.trim();
  const fields = plannerForm.fields
    .split(/[、,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (!businessName || !objectName || !fields.length) return "";
  const statuses = plannerForm.statuses
    .split(/[、,，\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const promptLines = [promptTemplatePreview.value];
  if (statuses.length) promptLines.push(`${template.optional_label}：${statuses.join("、")}`);
  const notes = plannerForm.notes.trim();
  if (notes) promptLines.push(`补充要求：${notes}`);
  promptLines.push("请先输出字段、列表、表单、详情、操作和权限方案，等待用户确认后再创建草稿，不要直接执行不可逆操作。");
  return promptLines.join("\n");
});

onMounted(async () => {
  if (!canConfigureAi.value) return;
  try {
    Object.assign(config, await api<AiConfig>("/ai/config/"));
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "无法加载 AI 配置");
  }
});

async function saveConfig() {
  saving.value = true;
  try {
    const payload: Record<string, unknown> = { ...config };
    if (apiKey.value) payload.api_key = apiKey.value;
    Object.assign(config, await api<AiConfig>("/ai/config/", { method: "PATCH", body: payload }));
    apiKey.value = "";
    ElMessage.success("AI 配置已保存");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存 AI 配置失败");
  } finally {
    saving.value = false;
  }
}

async function ensureConversation() {
  if (conversationId.value) return;
  const result = await api<{ id: number }>("/ai/conversations/", { method: "POST", body: {} });
  conversationId.value = result.id;
}

async function sendMessage() {
  const text = content.value.trim();
  if (!text || sending.value) return;
  sending.value = true;
  content.value = "";
  messages.value.push({ role: "user", content: text });
  messages.value.push({ role: "assistant", content: "" });
  const assistant = messages.value[messages.value.length - 1];
  try {
    await ensureConversation();
    const response = await apiStream("/ai/chat/", { conversation_id: conversationId.value, content: text });
    if (!response.body) throw new Error("AI 服务没有返回流");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const chunk = await reader.read();
      if (chunk.done) break;
      buffer += decoder.decode(chunk.value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";
      for (const event of events) {
        const dataLine = event.split("\n").find((line) => line.startsWith("data: "));
        if (!dataLine) continue;
        const data = JSON.parse(dataLine.slice(6));
        if (event.includes("event: token")) assistant.content += data.content;
        if (event.includes("event: error")) throw new Error(data.message);
      }
    }
  } catch (error) {
    assistant.content = error instanceof Error ? error.message : "AI 请求失败";
  } finally {
    sending.value = false;
  }
}

async function planFeature() {
  const text = generatedPrompt.value.trim();
  if (!text || planning.value) return;
  planning.value = true;
  try {
    proposal.value = await api<FeatureProposal>("/ai/feature-plan/", {
      method: "POST",
      body: { requirement: text },
    });
    ElMessage.success("功能方案已生成，请确认后创建");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "生成方案失败");
  } finally {
    planning.value = false;
  }
}

function applyPromptTemplate(key: string) {
  const template = promptTemplates.find((item) => item.key === key);
  if (!template) return;
  selectedTemplate.value = key;
  Object.assign(plannerForm, {
    business_name: template.business_name,
    object_name: template.object_name,
    fields: template.fields,
    statuses: template.statuses,
    notes: template.notes,
  });
  optionalPlannerOpen.value = template.statuses.trim() || template.notes.trim() ? ["optional"] : [];
}

async function confirmProposal() {
  if (!proposal.value || confirming.value) return;
  confirming.value = true;
  try {
    const result = await api<{ proposal: FeatureProposal; feature: { id: string } }>(
      `/ai/feature-proposals/${proposal.value.id}/confirm/`,
      { method: "POST", body: {} },
    );
    proposal.value = result.proposal;
    ElMessage.success("已创建草稿功能，请发布后使用");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "确认方案失败");
  } finally {
    confirming.value = false;
  }
}

async function publishProposal() {
  if (!proposal.value?.feature_id || confirming.value) return;
  confirming.value = true;
  try {
    await api(`/features/${proposal.value.feature_id}/publish/`, { method: "POST", body: {} });
    ElMessage.success("功能已发布");
    await routerPushFeature(proposal.value.feature_id);
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "发布功能失败");
  } finally {
    confirming.value = false;
  }
}

async function rejectProposal() {
  if (!proposal.value) return;
  try {
    await api(`/ai/feature-proposals/${proposal.value.id}/reject/`, { method: "POST", body: {} });
    proposal.value = null;
    ElMessage.success("方案已撤销");
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "撤销方案失败");
  }
}

async function routerPushFeature(featureId: string) {
  window.location.href = `/features/${featureId}`;
}
</script>

<template>
  <div class="page-header">
    <div>
      <div class="eyebrow">ASSISTANT</div>
      <h1>AI 助手</h1>
      <p>API Key 只保存在服务端，AI 通过受控功能接口参与业务创建。</p>
    </div>
  </div>

  <div class="ai-layout" :class="{ 'single-section': !canConfigureAi || !canUseAi }">
    <section v-if="canConfigureAi" class="surface-section config-section">
      <div class="section-heading">
        <div>
          <h2>模型配置</h2>
          <p>推荐使用 DeepSeek，只需填写 API Key，其他内容保持默认即可。</p>
        </div>
        <el-tag :type="config.has_api_key ? 'success' : 'info'" size="small">
          {{ config.has_api_key ? "已配置 Key" : "未配置 Key" }}
        </el-tag>
      </div>
      <el-form label-position="top">
        <el-form-item label="AI 服务">
          <el-input model-value="DeepSeek" disabled />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="apiKey" type="password" show-password placeholder="请输入 DeepSeek API Key" />
        </el-form-item>
        <el-checkbox v-model="config.is_enabled">启用当前配置</el-checkbox>
        <el-button type="primary" :loading="saving" class="config-save" @click="saveConfig">保存配置</el-button>
      </el-form>
      <el-collapse v-model="advancedConfigOpen" class="ai-advanced-config">
        <el-collapse-item title="高级配置" name="advanced">
          <p class="advanced-config-note">用于调整兼容接口地址或模型名称。普通使用无需修改。</p>
          <el-form label-position="top">
            <el-form-item label="Base URL">
              <el-input v-model="config.base_url" placeholder="例如：https://api.deepseek.com" />
            </el-form-item>
            <el-form-item label="模型">
              <el-input v-model="config.model" placeholder="例如：deepseek-v4-flash" />
            </el-form-item>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </section>

    <section v-if="canUseAi" class="surface-section ai-workspace-section">
      <div class="section-heading">
        <div>
          <h2>AI 工作区</h2>
          <p>{{ canManageFeatures ? "选择一种方式开始，当前只展示一个工作区。" : "输入问题或需求，与 AI 进行对话。" }}</p>
        </div>
      </div>
      <el-tabs v-model="activeWorkspaceMode" class="ai-workspace-tabs">
        <el-tab-pane v-if="canManageFeatures" label="创建功能" name="planner">
          <div class="feature-planner">
            <div class="planner-heading">
              <strong>按模板填写关键信息</strong>
              <span>AI 会继续补齐页面、操作和权限。</span>
            </div>
        <div class="planner-template-bar">
          <span class="planner-template-label">提示词模板</span>
          <el-select v-model="selectedTemplate" class="planner-template-select" @change="applyPromptTemplate">
          <el-option v-for="template in promptTemplates" :key="template.key" :label="template.label" :value="template.key">
            <div class="planner-template-option">
              <strong>{{ template.label }}</strong>
              <small>{{ template.description }}</small>
            </div>
          </el-option>
        </el-select>
          <el-button link class="planner-clear-button" @click="applyPromptTemplate('custom')">清空重新描述</el-button>
        </div>
        <div class="planner-template-preview">
          <div class="planner-template-preview-label">模板预览</div>
          <p>{{ promptTemplatePreview }}</p>
          <p v-if="plannerForm.statuses.trim()" class="planner-template-preview-extra">{{ selectedTemplateDefinition.optional_label }}：{{ plannerForm.statuses }}</p>
          <p v-if="plannerForm.notes.trim()" class="planner-template-preview-extra">补充要求：{{ plannerForm.notes }}</p>
        </div>
        <el-form label-position="top" class="planner-form">
          <div class="planner-key-fields-grid">
            <el-form-item :label="selectedTemplateDefinition.business_label" required>
              <el-input v-model="plannerForm.business_name" :placeholder="selectedTemplateDefinition.business_placeholder" />
            </el-form-item>
            <el-form-item :label="selectedTemplateDefinition.object_label" required>
              <el-input v-model="plannerForm.object_name" :placeholder="selectedTemplateDefinition.object_placeholder" />
            </el-form-item>
            <el-form-item :label="selectedTemplateDefinition.fields_label" required>
              <el-input v-model="plannerForm.fields" :placeholder="selectedTemplateDefinition.fields_placeholder" />
            </el-form-item>
          </div>
          <el-collapse v-model="optionalPlannerOpen" class="planner-extra-collapse">
            <el-collapse-item title="补充信息（可选）" name="optional">
              <p class="planner-extra-note">不确定的内容可以留空，AI 会根据业务场景判断。</p>
              <div class="planner-fields-grid">
                <el-form-item :label="selectedTemplateDefinition.optional_label">
                  <el-input v-model="plannerForm.statuses" :placeholder="selectedTemplateDefinition.optional_placeholder" />
                </el-form-item>
                <el-form-item label="补充要求">
                  <el-input v-model="plannerForm.notes" type="textarea" :rows="2" resize="none" placeholder="例如：需要手机号格式校验" />
                </el-form-item>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-form>
        <div v-if="generatedPrompt" class="planner-prompt-preview">
          <div class="planner-prompt-label">将发送给 AI 的提示词</div>
          <el-input :model-value="generatedPrompt" type="textarea" :rows="6" readonly resize="none" />
        </div>
        <div class="planner-actions">
          <el-button type="primary" :loading="planning" :disabled="!generatedPrompt" @click="planFeature">让 AI 生成方案</el-button>
        </div>
        <div v-if="proposal" class="proposal-preview">
          <div class="proposal-title">
            <div>
              <strong>{{ proposal.name }}</strong>
              <span>{{ proposal.key }}</span>
            </div>
            <el-tag :type="proposal.status === 'proposed' ? 'warning' : proposal.status === 'created' ? 'info' : 'danger'" size="small">
              {{ proposal.status === "proposed" ? "待确认" : proposal.status === "created" ? "草稿" : "已撤销" }}
            </el-tag>
          </div>
          <p>{{ proposal.description || "暂无说明" }}</p>
          <div class="proposal-fields">
            <el-tag v-for="field in proposal.manifest.fields" :key="field.key" size="small" effect="plain">
              {{ field.label }} · {{ field.type }}
            </el-tag>
          </div>
          <div class="proposal-actions">
            <el-button v-if="proposal.status === 'proposed'" type="primary" :loading="confirming" @click="confirmProposal">确认创建草稿</el-button>
            <el-button v-if="proposal.status === 'proposed'" type="danger" plain @click="rejectProposal">撤销方案</el-button>
            <el-button v-if="proposal.status === 'created'" type="primary" :loading="confirming" @click="publishProposal">确认发布</el-button>
          </div>
        </div>
          </div>
        </el-tab-pane>
        <el-tab-pane label="自由对话" name="chat">
          <div class="chat-pane">
            <div class="message-list" :class="{ 'is-empty': !messages.length }">
              <div v-if="!messages.length" class="empty-chat">例如：帮我创建一个客户管理，包含名称、联系人和跟进状态。</div>
              <div v-for="(message, index) in messages" :key="index" class="message-row" :class="message.role">
                <span class="message-role">{{ message.role === "user" ? "你" : "AI" }}</span>
                <div class="message-content">{{ message.content || "正在思考..." }}</div>
              </div>
            </div>
            <div class="chat-composer">
              <el-input v-model="content" type="textarea" :rows="3" resize="none" placeholder="输入需求" @keydown.ctrl.enter="sendMessage" />
              <el-button type="primary" :loading="sending" :disabled="!content.trim()" @click="sendMessage">发送</el-button>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </section>
  </div>
</template>
