// Temporary stand-in for real authentication. The API's `X-Tenant-Id`
// header (see apps/api's get_current_tenant_id) is NOT an auth
// mechanism — it trusts whatever UUID the caller sends, as long as it
// names a real Tenant row. Until real auth exists, this dashboard just
// remembers a tenant id the operator pastes in once (e.g. from a Tenant
// created via a backend script/test fixture), persisted in
// localStorage so it survives a reload. Nothing here should be mistaken
// for a login.
const STORAGE_KEY = "studio.tenantId";

export function getStoredTenantId(): string {
  try {
    return window.localStorage.getItem(STORAGE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setStoredTenantId(tenantId: string): void {
  try {
    if (tenantId) {
      window.localStorage.setItem(STORAGE_KEY, tenantId);
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  } catch {
    // localStorage can throw (private mode, disabled storage) — losing
    // the remembered tenant id is a minor inconvenience, not a failure
    // worth surfacing to the user.
  }
}
