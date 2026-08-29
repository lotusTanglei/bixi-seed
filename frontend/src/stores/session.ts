import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { api, ApiError } from "../api/http";

export interface OrganizationMembership {
  id: string;
  name: string;
  slug?: string;
  parent_id: string | null;
  parent_name: string | null;
  path: string;
  role: string;
  is_owner: boolean;
  permissions: string[];
}

interface User {
  id: number;
  username: string;
  email: string;
  display_name: string;
  contact: string;
  is_staff: boolean;
  is_superuser: boolean;
}

interface SessionPayload {
  user: User;
  organizations: OrganizationMembership[];
  active_organization: string | null;
}

export const useSessionStore = defineStore("session", () => {
  const user = ref<User | null>(null);
  const organizations = ref<OrganizationMembership[]>([]);
  const activeOrganizationId = ref<string | null>(null);
  const initialized = ref(false);
  const loading = ref(false);
  const isAuthenticated = computed(() => user.value !== null);
  const activeOrganization = computed(() => organizations.value.find((item) => item.id === activeOrganizationId.value));

  function apply(payload: SessionPayload) {
    user.value = payload.user;
    organizations.value = payload.organizations;
    activeOrganizationId.value = payload.active_organization;
  }

  async function load() {
    if (initialized.value) return;
    loading.value = true;
    try {
      apply(await api<SessionPayload>("/auth/me/"));
    } catch (error) {
      if (error instanceof ApiError && ![401, 403].includes(error.status)) {
        console.error("无法加载登录状态", error);
      }
      user.value = null;
    } finally {
      initialized.value = true;
      loading.value = false;
    }
  }

  async function login(username: string, password: string) {
    apply(await api<SessionPayload>("/auth/login/", { method: "POST", body: { username, password } }));
    initialized.value = true;
  }

  async function refresh() {
    apply(await api<SessionPayload>("/auth/me/"));
    initialized.value = true;
  }

  async function createOrganization(name: string, parentId: string | null = null) {
    const organization = await api<{ id: string }>("/organizations/", {
      method: "POST",
      body: { name, parent_id: parentId },
    });
    await switchOrganization(organization.id);
    await refresh();
  }

  function hasPermission(permission: string) {
    return Boolean(user.value?.is_superuser || activeOrganization.value?.is_owner || activeOrganization.value?.permissions.includes(permission));
  }

  function hasAnyPermission(permissions: string[]) {
    return permissions.some((permission) => hasPermission(permission));
  }

  async function logout() {
    await api("/auth/logout/", { method: "POST", body: {} });
    user.value = null;
    organizations.value = [];
    activeOrganizationId.value = null;
  }

  async function switchOrganization(organizationId: string) {
    await api("/auth/switch-organization/", { method: "POST", body: { organization_id: organizationId } });
    activeOrganizationId.value = organizationId;
  }

  return {
    user,
    organizations,
    activeOrganizationId,
    activeOrganization,
    initialized,
    loading,
    isAuthenticated,
    load,
    login,
    refresh,
    createOrganization,
    hasPermission,
    hasAnyPermission,
    logout,
    switchOrganization,
  };
});
