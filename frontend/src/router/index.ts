import { createRouter, createWebHistory } from "vue-router";

import DashboardView from "../views/DashboardView.vue";
import LoginView from "../views/LoginView.vue";
import OrganizationsView from "../views/OrganizationsView.vue";
import AiView from "../views/AiView.vue";
import FeatureView from "../views/FeatureView.vue";
import SettingsView from "../views/SettingsView.vue";
import ExtensionsView from "../views/ExtensionsView.vue";
import { useSessionStore } from "../stores/session";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: LoginView },
    { path: "/", name: "dashboard", component: DashboardView, meta: { requiresAuth: true } },
    {
      path: "/organizations",
      name: "organizations",
      component: OrganizationsView,
      meta: { requiresAuth: true, permissions: ["member.read", "member.manage", "role.manage", "audit.read", "organization.manage"] },
    },
    { path: "/ai", name: "ai", component: AiView, meta: { requiresAuth: true, permissions: ["ai.use", "ai.configure"] } },
    { path: "/settings", name: "settings", component: SettingsView, meta: { requiresAuth: true, permissions: ["organization.manage"] } },
    { path: "/extensions", name: "extensions", component: ExtensionsView, meta: { requiresAuth: true, permissions: ["feature.manage"] } },
    { path: "/features/:featureId", name: "feature", component: FeatureView, meta: { requiresAuth: true, permissions: ["feature.read", "feature.manage"] } },
  ],
});

router.beforeEach(async (to) => {
  const session = useSessionStore();
  await session.load();
  if (to.meta.requiresAuth && !session.isAuthenticated) return { name: "login" };
  if (to.name === "login" && session.isAuthenticated) return { name: "dashboard" };
  const permissions = to.meta.permissions as string[] | undefined;
  if (permissions?.length && !session.hasAnyPermission(permissions)) return { name: "dashboard" };
  return true;
});

export default router;
