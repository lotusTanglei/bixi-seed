<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Delete, Edit, Plus, Refresh, Setting, VideoPause, VideoPlay } from "@element-plus/icons-vue";

import { api } from "../api/http";
import { useSessionStore, type OrganizationMembership } from "../stores/session";

interface Member {
  id: number;
  username: string;
  email: string;
  display_name: string;
  contact: string;
  role: string;
  role_id: number;
  is_owner: boolean;
  is_active: boolean;
  status: "invited" | "active" | "disabled";
  invited_at?: string | null;
  accepted_at?: string | null;
  created_at: string;
}

interface Invitation {
  id: number;
  username: string;
  display_name: string;
  role: string;
  role_id: number;
  expires_at: string;
  created_at: string;
  status: string;
}

interface Role {
  id: number;
  code: string;
  name: string;
  description: string;
  is_system: boolean;
  member_count: number;
  permissions: string[];
}

interface Permission {
  code: string;
  name: string;
  description: string;
  menu_code: string;
  menu_name: string;
  action: string;
  assignable?: boolean;
}

interface OrganizationTreeNode extends OrganizationMembership {
  children: OrganizationTreeNode[];
}

interface AuditLog {
  id: number;
  actor: string;
  action: string;
  object_type: string;
  object_id: string;
  metadata: Record<string, unknown>;
  success: boolean;
  created_at: string;
}

const members = ref<Member[]>([]);
const roles = ref<Role[]>([]);
const permissions = ref<Permission[]>([]);
const auditLogs = ref<AuditLog[]>([]);
const invitations = ref<Invitation[]>([]);
const auditPagination = reactive({ page: 1, page_size: 20, total: 0 });
const auditFilters = reactive({ action: "", object_type: "", success: "", date_from: "", date_to: "" });
const loading = ref(true);
const memberDialog = ref(false);
const roleDialog = ref(false);
const permissionDialog = ref(false);
const memberSaving = ref(false);
const roleSaving = ref(false);
const permissionSaving = ref(false);
const organizationDialog = ref(false);
const organizationName = ref("");
const organizationParentId = ref<string | null>(null);
const organizationSaving = ref(false);
const inviteDialog = ref(false);
const inviteSaving = ref(false);
const inviteToken = ref("");
const inviteForm = reactive({ username: "", display_name: "", contact: "", role_id: 0 });
const transferSaving = ref(false);
const editingRole = ref<Role | null>(null);
const permissionRole = ref<Role | null>(null);
const editingMember = ref<Member | null>(null);
const memberForm = reactive({ username: "", display_name: "", contact: "", password: "", role_id: 0 });
const roleForm = reactive({ code: "", name: "", description: "" });
const permissionForm = reactive({ permissions: [] as string[] });
const session = useSessionStore();

const canReadMembers = computed(() => session.hasAnyPermission(["member.read", "member.manage"]));
const canManageMembers = computed(() => session.hasPermission("member.manage"));
const canManageRoles = computed(() => session.hasPermission("role.manage"));
const canReadAudit = computed(() => session.hasPermission("audit.read"));
const organizationTree = computed<OrganizationTreeNode[]>(() => {
  const nodes = new Map(
    session.organizations.map((organization) => [organization.id, { ...organization, children: [] } as OrganizationTreeNode]),
  );
  const roots: OrganizationTreeNode[] = [];
  nodes.forEach((node) => {
    const parent = node.parent_id ? nodes.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  return roots;
});
const permissionGroups = computed(() => {
  const groups = new Map<string, { code: string; name: string; permissions: Permission[] }>();
  permissions.value.forEach((permission) => {
    const group = groups.get(permission.menu_code) ?? {
      code: permission.menu_code,
      name: permission.menu_name,
      permissions: [],
    };
    group.permissions.push(permission);
    groups.set(permission.menu_code, group);
  });
  const order = ["organizations", "ai", "features", "other"];
  return [...groups.values()].sort((left, right) => {
    const leftIndex = order.indexOf(left.code);
    const rightIndex = order.indexOf(right.code);
    return (leftIndex < 0 ? order.length : leftIndex) - (rightIndex < 0 ? order.length : rightIndex);
  });
});

const selectedPermissionCount = computed(() => permissionForm.permissions.length);

function groupSelectedCount(group: { permissions: Permission[] }) {
  return group.permissions.filter((permission) => permissionForm.permissions.includes(permission.code)).length;
}

function isGroupSelected(group: { permissions: Permission[] }) {
  return groupSelectedCount(group) === group.permissions.length && group.permissions.length > 0;
}

function isGroupIndeterminate(group: { permissions: Permission[] }) {
  const selectedCount = groupSelectedCount(group);
  return selectedCount > 0 && selectedCount < group.permissions.length;
}

function togglePermissionGroup(group: { permissions: Permission[] }, checked: boolean) {
  const groupCodes = group.permissions.map((permission) => permission.code);
  if (checked) {
    permissionForm.permissions = [...new Set([...permissionForm.permissions, ...groupCodes.filter((code) => {
      const permission = group.permissions.find((item) => item.code === code);
      return permission?.assignable !== false;
    })])];
  } else {
    permissionForm.permissions = permissionForm.permissions.filter((code) => !groupCodes.includes(code));
  }
}

function openOrganizationDialog() {
  organizationName.value = "";
  organizationParentId.value = session.hasPermission("organization.manage") ? session.activeOrganizationId : null;
  organizationDialog.value = true;
}

async function createOrganization() {
  const name = organizationName.value.trim();
  if (!name || organizationSaving.value) return;
  organizationSaving.value = true;
  try {
    await session.createOrganization(name, organizationParentId.value);
    organizationDialog.value = false;
    ElMessage.success("组织已创建并切换");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "创建组织失败");
  } finally {
    organizationSaving.value = false;
  }
}

function openInviteDialog() {
  inviteForm.username = "";
  inviteForm.display_name = "";
  inviteForm.contact = "";
  inviteForm.role_id = roles.value.find((role) => role.code === "member")?.id ?? roles.value[0]?.id ?? 0;
  inviteToken.value = "";
  inviteDialog.value = true;
}

async function inviteMember() {
  inviteSaving.value = true;
  try {
    const response = await api<{ token: string }>("/organizations/invitations/", {
      method: "POST",
      body: { ...inviteForm },
    });
    inviteToken.value = response.token;
    ElMessage.success("邀请已生成");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "生成邀请失败");
  } finally {
    inviteSaving.value = false;
  }
}

async function revokeInvitation(invitation: Invitation) {
  try {
    await ElMessageBox.confirm(`确定撤销 ${invitation.username} 的邀请？`, "撤销邀请", { type: "warning" });
    await api(`/organizations/invitations/${invitation.id}/`, { method: "DELETE" });
    ElMessage.success("邀请已撤销");
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error instanceof Error ? error.message : "撤销邀请失败");
  }
}

async function transferOwner(member: Member) {
  try {
    await ElMessageBox.confirm(`确定将所有权转移给 ${member.display_name}？`, "转移所有权", { type: "warning" });
    transferSaving.value = true;
    await api("/organizations/transfer-owner/", { method: "POST", body: { user_id: member.id, confirm: true } });
    await session.refresh();
    ElMessage.success("所有权已转移");
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error instanceof Error ? error.message : "转移所有权失败");
  } finally {
    transferSaving.value = false;
  }
}

async function leaveOrganization() {
  try {
    await ElMessageBox.confirm("退出后将无法继续访问当前组织，确定继续？", "退出组织", { type: "warning" });
    await api("/organizations/leave/", { method: "POST", body: {} });
    await session.refresh();
    ElMessage.success("已退出组织");
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close") ElMessage.error(error instanceof Error ? error.message : "退出组织失败");
  }
}

async function load() {
  loading.value = true;
  try {
    const results = await Promise.all([
      canReadMembers.value ? api<Member[]>("/organizations/members/").catch(() => null) : Promise.resolve(null),
      canManageRoles.value ? api<Role[]>("/organizations/roles/").catch(() => null) : Promise.resolve(null),
      canManageRoles.value ? api<Permission[]>("/organizations/permissions/").catch(() => null) : Promise.resolve(null),
      canReadAudit.value ? api<{ items: AuditLog[]; pagination: typeof auditPagination }>(`/organizations/audit-logs/?page=${auditPagination.page}&page_size=${auditPagination.page_size}&${new URLSearchParams(Object.entries(auditFilters).filter(([, value]) => value) as string[][]).toString()}`).catch(() => null) : Promise.resolve(null),
      canManageMembers.value ? api<Invitation[]>("/organizations/invitations/").catch(() => null) : Promise.resolve(null),
    ]);
    members.value = results[0] ?? [];
    roles.value = results[1] ?? [];
    permissions.value = results[2] ?? [];
    const audit = results[3] as { items: AuditLog[]; pagination: typeof auditPagination } | null;
    auditLogs.value = audit?.items ?? [];
    if (audit?.pagination) Object.assign(auditPagination, audit.pagination);
    invitations.value = (results[4] as Invitation[] | null) ?? [];
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "无法加载组织数据");
  } finally {
    loading.value = false;
  }
}

function applyAuditFilters() {
  auditPagination.page = 1;
  load();
}

async function selectOrganization(node: OrganizationTreeNode) {
  if (node.id === session.activeOrganizationId) return;
  try {
    await session.switchOrganization(node.id);
    ElMessage.success(`已切换到${node.name}`);
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "切换组织失败");
  }
}

function openMemberDialog(member?: Member) {
  editingMember.value = member ?? null;
  memberForm.username = member?.username ?? "";
  memberForm.display_name = member?.display_name ?? "";
  memberForm.contact = member?.contact ?? "";
  memberForm.password = "";
  memberForm.role_id = member?.role_id ?? roles.value.find((role) => role.code === "member")?.id ?? roles.value[0]?.id ?? 0;
  memberDialog.value = true;
}

async function saveMember() {
  memberSaving.value = true;
  try {
    if (editingMember.value) {
      await api<Member>(`/organizations/members/${editingMember.value.id}/`, {
        method: "PATCH",
        body: { display_name: memberForm.display_name, contact: memberForm.contact, role_id: memberForm.role_id },
      });
    } else {
      await api<Member>("/organizations/members/", { method: "POST", body: { ...memberForm } });
    }
    memberDialog.value = false;
    ElMessage.success(editingMember.value ? "成员资料已更新" : "成员已加入组织");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存成员失败");
  } finally {
    memberSaving.value = false;
  }
}

async function toggleMember(member: Member) {
  try {
    await api<Member>(`/organizations/members/${member.id}/`, {
      method: "PATCH",
      body: { is_active: !member.is_active },
    });
    ElMessage.success(member.is_active ? "成员已停用" : "成员已恢复");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新成员失败");
  }
}

async function removeMember(member: Member) {
  try {
    await ElMessageBox.confirm(`确定移除 ${member.display_name}（${member.username}）？`, "移除成员", { type: "warning" });
    await api(`/organizations/members/${member.id}/`, { method: "DELETE" });
    ElMessage.success("成员已移除");
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close") {
      ElMessage.error(error instanceof Error ? error.message : "移除成员失败");
    }
  }
}

function openRoleDialog(role?: Role) {
  editingRole.value = role ?? null;
  roleForm.code = role?.code ?? "";
  roleForm.name = role?.name ?? "";
  roleForm.description = role?.description ?? "";
  roleDialog.value = true;
}

function openPermissionDialog(role: Role) {
  permissionRole.value = role;
  permissionForm.permissions = [...role.permissions];
  permissionDialog.value = true;
}

async function saveRole() {
  roleSaving.value = true;
  try {
    const creating = !editingRole.value;
    let savedRole: Role;
    if (editingRole.value) {
      savedRole = await api<Role>(`/organizations/roles/${editingRole.value.id}/`, {
        method: "PATCH",
        body: { name: roleForm.name, description: roleForm.description },
      });
    } else {
      savedRole = await api<Role>("/organizations/roles/", { method: "POST", body: { ...roleForm, permissions: [] } });
    }
    roleDialog.value = false;
    await load();
    ElMessage.success(creating ? "角色已创建，请继续配置菜单权限" : "角色资料已保存");
    if (creating) {
      openPermissionDialog(roles.value.find((role) => role.id === savedRole.id) ?? savedRole);
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存角色失败");
  } finally {
    roleSaving.value = false;
  }
}

async function savePermissions() {
  if (!permissionRole.value || permissionRole.value.is_system) return;
  permissionSaving.value = true;
  try {
    await api<Role>(`/organizations/roles/${permissionRole.value.id}/`, {
      method: "PATCH",
      body: { permissions: permissionForm.permissions },
    });
    permissionDialog.value = false;
    ElMessage.success("菜单权限已保存");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "保存菜单权限失败");
  } finally {
    permissionSaving.value = false;
  }
}

async function deleteRole(role: Role) {
  try {
    await ElMessageBox.confirm(`确定删除角色“${role.name}”？`, "删除角色", { type: "warning" });
    await api(`/organizations/roles/${role.id}/`, { method: "DELETE" });
    ElMessage.success("角色已删除");
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close") {
      ElMessage.error(error instanceof Error ? error.message : "删除角色失败");
    }
  }
}

async function changeMemberRole(member: Member, roleId: number) {
  try {
    await api<Member>(`/organizations/members/${member.id}/`, { method: "PATCH", body: { role_id: roleId } });
    ElMessage.success("成员角色已更新");
    await load();
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : "更新角色失败");
    await load();
  }
}

onMounted(load);
</script>

<template>
  <div class="page-header">
    <div>
      <div class="eyebrow">ACCESS CONTROL</div>
      <h1>组织权限</h1>
      <p>管理成员、角色和组织范围内的访问记录。</p>
    </div>
    <el-button :icon="Refresh" circle title="刷新" aria-label="刷新" @click="load" />
  </div>

  <div class="organization-toolbar">
    <el-button v-if="canManageMembers" type="primary" :icon="Plus" @click="openInviteDialog">邀请成员</el-button>
    <el-button v-if="canManageMembers" :icon="Plus" @click="openMemberDialog()">直接加入</el-button>
    <el-button v-if="canManageRoles" :icon="Plus" @click="openRoleDialog()">新增角色</el-button>
  </div>

  <section class="surface-section organization-hierarchy-section">
    <div class="section-heading organization-hierarchy-heading">
      <div>
        <h2>组织架构</h2>
        <p>当前账号可访问的组织树，点击组织可以切换当前范围。</p>
      </div>
      <el-button type="primary" :icon="Plus" @click="openOrganizationDialog">新建组织</el-button>
    </div>
    <el-tree
      v-if="organizationTree.length"
      :data="organizationTree"
      node-key="id"
      default-expand-all
      :expand-on-click-node="false"
      @node-click="selectOrganization"
    >
      <template #default="{ data }">
        <div class="organization-tree-node" :class="{ 'is-active': data.id === session.activeOrganizationId }">
          <strong>{{ data.name }}</strong>
          <small>{{ data.path }} · {{ data.role }}</small>
        </div>
      </template>
    </el-tree>
    <el-empty v-else description="暂无可访问组织" />
  </section>

  <div class="two-column-layout" v-loading="loading">
    <section v-if="canReadMembers" class="surface-section">
      <div class="section-heading">
        <div>
          <h2>成员管理</h2>
          <p>{{ members.length }} 位组织成员</p>
        </div>
      </div>
      <el-table :data="members" size="small" empty-text="暂无成员">
        <el-table-column label="成员" min-width="170">
          <template #default="{ row }">
            <strong>{{ row.display_name }}</strong>
            <small class="table-secondary">账号：{{ row.username }}</small>
            <small class="table-secondary">联系方式：{{ row.contact || "未填写" }}</small>
          </template>
        </el-table-column>
        <el-table-column label="角色" min-width="150">
          <template #default="{ row }">
            <el-select
              v-if="!row.is_owner"
              :model-value="row.role_id"
              size="small"
              @change="(value: number) => changeMemberRole(row, value)"
            >
              <el-option v-for="role in roles.filter((item) => item.code !== 'owner')" :key="role.id" :label="role.name" :value="role.id" />
            </el-select>
            <span v-else>{{ row.role }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag v-if="row.is_owner" type="warning" size="small">所有者</el-tag>
            <el-tag v-else-if="row.is_active" type="success" size="small">正常</el-tag>
            <el-tag v-else type="info" size="small">已停用</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <template v-if="!row.is_owner">
              <el-button v-if="canManageMembers" link :icon="Edit" title="编辑成员资料" aria-label="编辑成员资料" @click="openMemberDialog(row)" />
              <el-button
                v-if="canManageMembers"
                link
                :type="row.is_active ? 'warning' : 'success'"
                :icon="row.is_active ? VideoPause : VideoPlay"
                :title="row.is_active ? '停用成员' : '恢复成员'"
                :aria-label="row.is_active ? '停用成员' : '恢复成员'"
                @click="toggleMember(row)"
              />
              <el-button v-if="canManageMembers" link type="danger" :icon="Delete" title="移除成员" aria-label="移除成员" @click="removeMember(row)" />
              <el-button v-if="session.activeOrganization?.is_owner" link title="转移所有权" aria-label="转移所有权" @click="transferOwner(row)">转移所有权</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section v-if="canManageRoles" class="surface-section">
      <div class="section-heading">
        <div>
          <h2>角色权限</h2>
          <p>按角色控制菜单访问和操作范围，共 {{ roles.length }} 个角色</p>
        </div>
      </div>
      <div class="role-list">
        <div v-for="role in roles" :key="role.id" class="role-row">
          <div>
            <strong>{{ role.name }}</strong>
            <span>{{ role.code }} · {{ role.member_count }} 名成员 · {{ role.permissions.length }} 项权限</span>
            <small class="role-description">{{ role.description || "未填写角色说明" }}</small>
          </div>
          <div class="row-actions">
            <el-button v-if="canManageRoles" link :icon="Setting" @click="openPermissionDialog(role)">
              {{ role.is_system ? "查看权限" : "配置权限" }}
            </el-button>
            <el-button v-if="canManageRoles && !role.is_system" link :icon="Edit" title="编辑角色" aria-label="编辑角色" @click="openRoleDialog(role)" />
            <el-button v-if="canManageRoles && !role.is_system" link type="danger" :icon="Delete" title="删除角色" aria-label="删除角色" @click="deleteRole(role)" />
          </div>
        </div>
      </div>
    </section>
  </div>

  <section v-if="canManageMembers && invitations.length" class="surface-section invitation-section" v-loading="loading">
    <div class="section-heading"><div><h2>待接受邀请</h2><p>{{ invitations.length }} 个邀请等待接受。</p></div></div>
    <el-table :data="invitations" size="small">
      <el-table-column prop="username" label="待接受账号" />
      <el-table-column prop="role" label="角色" />
      <el-table-column prop="expires_at" label="过期时间" />
      <el-table-column label="操作" width="90"><template #default="{ row }"><el-button link type="danger" @click="revokeInvitation(row)">撤销</el-button></template></el-table-column>
    </el-table>
  </section>

  <section v-if="canReadAudit" class="surface-section audit-section" v-loading="loading">
    <div class="section-heading">
      <div>
        <h2>操作审计</h2>
        <p>组织变更和 AI 操作记录。</p>
      </div>
    </div>
    <div class="audit-filters">
      <el-input v-model="auditFilters.action" clearable placeholder="操作" @keyup.enter="applyAuditFilters" />
      <el-input v-model="auditFilters.object_type" clearable placeholder="对象类型" @keyup.enter="applyAuditFilters" />
      <el-select v-model="auditFilters.success" clearable placeholder="结果"><el-option label="成功" value="true" /><el-option label="失败" value="false" /></el-select>
      <el-date-picker v-model="auditFilters.date_from" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" />
      <el-date-picker v-model="auditFilters.date_to" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" />
      <el-button :icon="Refresh" @click="applyAuditFilters">筛选</el-button>
    </div>
    <el-table :data="auditLogs" size="small" empty-text="暂无审计记录">
      <el-table-column prop="created_at" label="时间" width="190" />
      <el-table-column prop="actor" label="操作者" width="160" />
      <el-table-column prop="action" label="操作" min-width="190" />
      <el-table-column prop="object_type" label="对象" width="150" />
      <el-table-column label="结果" width="80">
        <template #default="{ row }">
          <el-tag :type="row.success ? 'success' : 'danger'" size="small">{{ row.success ? "成功" : "失败" }}</el-tag>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="auditPagination.total > auditPagination.page_size" v-model:current-page="auditPagination.page" :page-size="auditPagination.page_size" layout="total, prev, pager, next" :total="auditPagination.total" @current-change="load" />
  </section>

  <section v-if="session.activeOrganization && !session.activeOrganization.is_owner" class="organization-exit-actions">
    <el-button type="danger" plain @click="leaveOrganization">退出当前组织</el-button>
  </section>

  <el-dialog v-model="organizationDialog" title="新建组织" width="420px">
    <el-form label-position="top" @submit.prevent="createOrganization">
      <el-form-item label="组织名称" required>
        <el-input v-model="organizationName" maxlength="160" show-word-limit placeholder="例如：我的工作室" @keyup.enter="createOrganization" />
      </el-form-item>
      <el-form-item label="上级组织">
        <el-select v-model="organizationParentId" class="full-width" :disabled="!session.hasPermission('organization.manage')">
          <el-option label="作为顶级组织" :value="null" />
          <el-option
            v-for="item in session.organizations.filter((organization) => organization.is_owner || organization.permissions.includes('organization.manage'))"
            :key="item.id"
            :label="item.path || item.name"
            :value="item.id"
          />
        </el-select>
        <small v-if="!session.hasPermission('organization.manage')" class="form-hint">当前账号只能创建顶级组织，不能在现有组织下创建子组织。</small>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="organizationDialog = false">取消</el-button>
      <el-button type="primary" :loading="organizationSaving" :disabled="!organizationName.trim()" @click="createOrganization">创建组织</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="memberDialog" :title="editingMember ? '编辑成员资料' : '新增成员'" width="460px">
    <el-form label-position="top">
      <el-form-item label="账号" required><el-input v-model="memberForm.username" :disabled="Boolean(editingMember)" placeholder="例如 zhangsan" /></el-form-item>
      <el-form-item label="姓名" required><el-input v-model="memberForm.display_name" /></el-form-item>
      <el-form-item label="联系方式" required><el-input v-model="memberForm.contact" placeholder="手机号、微信号等" /></el-form-item>
      <el-form-item v-if="!editingMember" label="初始密码" required><el-input v-model="memberForm.password" type="password" show-password /></el-form-item>
      <el-form-item label="角色" required>
        <el-select v-model="memberForm.role_id" class="full-width">
          <el-option v-for="role in roles.filter((item) => item.code !== 'owner')" :key="role.id" :label="role.name" :value="role.id" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="memberDialog = false">取消</el-button>
      <el-button type="primary" :loading="memberSaving" :disabled="!memberForm.username || !memberForm.display_name || !memberForm.contact || (!editingMember && !memberForm.password) || !memberForm.role_id" @click="saveMember">保存</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="inviteDialog" title="邀请成员" width="460px">
    <el-form label-position="top">
      <el-form-item label="账号" required><el-input v-model="inviteForm.username" :disabled="Boolean(inviteToken)" /></el-form-item>
      <el-form-item label="姓名"><el-input v-model="inviteForm.display_name" :disabled="Boolean(inviteToken)" /></el-form-item>
      <el-form-item label="联系方式"><el-input v-model="inviteForm.contact" :disabled="Boolean(inviteToken)" /></el-form-item>
      <el-form-item label="角色" required><el-select v-model="inviteForm.role_id" class="full-width" :disabled="Boolean(inviteToken)"><el-option v-for="role in roles.filter((item) => item.code !== 'owner')" :key="role.id" :label="role.name" :value="role.id" /></el-select></el-form-item>
      <el-alert v-if="inviteToken" type="success" :closable="false" title="一次性邀请令牌" :description="inviteToken" />
    </el-form>
    <template #footer><el-button @click="inviteDialog = false">关闭</el-button><el-button v-if="!inviteToken" type="primary" :loading="inviteSaving" :disabled="!inviteForm.username || !inviteForm.role_id" @click="inviteMember">生成邀请</el-button></template>
  </el-dialog>

  <el-dialog v-model="roleDialog" :title="editingRole ? '编辑角色资料' : '新增角色'" width="460px">
    <el-form label-position="top">
      <el-form-item v-if="!editingRole" label="角色编码" required><el-input v-model="roleForm.code" placeholder="例如 sales" /></el-form-item>
      <el-form-item label="角色名称" required><el-input v-model="roleForm.name" /></el-form-item>
      <el-form-item label="描述"><el-input v-model="roleForm.description" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="roleDialog = false">取消</el-button>
      <el-button type="primary" :loading="roleSaving" :disabled="!roleForm.name || (!editingRole && !roleForm.code)" @click="saveRole">保存角色资料</el-button>
    </template>
  </el-dialog>

  <el-dialog v-model="permissionDialog" :title="`${permissionRole?.is_system ? '查看权限' : '配置权限'} · ${permissionRole?.name ?? ''}`" width="760px" class="permission-dialog">
    <div v-if="permissionRole" class="permission-dialog-summary">
      <div>
        <strong>{{ permissionRole.description || "未填写角色说明" }}</strong>
        <span>已选择 {{ selectedPermissionCount }} 项菜单权限</span>
      </div>
      <el-tag v-if="permissionRole.is_system" type="info">系统角色只读</el-tag>
    </div>
    <div v-if="permissionRole && !permissionRole.is_system" class="permission-dialog-note">只能授予当前账号已有的权限；未选中的权限不会开放给该角色。</div>
    <div class="permission-menu-grid">
      <section v-for="group in permissionGroups" :key="group.code" class="permission-menu-group">
        <div class="permission-menu-heading">
          <div>
            <strong>{{ group.name }}</strong>
            <span>{{ groupSelectedCount(group) }} / {{ group.permissions.length }} 项</span>
          </div>
          <el-checkbox
            :model-value="isGroupSelected(group)"
            :indeterminate="isGroupIndeterminate(group)"
            :disabled="permissionRole?.is_system"
            @change="(value: string | number | boolean) => togglePermissionGroup(group, Boolean(value))"
          >全选</el-checkbox>
        </div>
        <el-checkbox-group v-model="permissionForm.permissions" class="permission-options">
          <el-checkbox
            v-for="permission in group.permissions"
            :key="permission.code"
            :label="permission.code"
            :disabled="permissionRole?.is_system || permission.assignable === false"
          >
            <span class="permission-option-label">{{ permission.action }}</span>
            <small>{{ permission.description }}</small>
          </el-checkbox>
        </el-checkbox-group>
      </section>
    </div>
    <template #footer>
      <el-button @click="permissionDialog = false">关闭</el-button>
      <el-button v-if="!permissionRole?.is_system" type="primary" :loading="permissionSaving" @click="savePermissions">保存菜单权限</el-button>
    </template>
  </el-dialog>
</template>
