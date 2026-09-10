"use client";

import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { fetchApi } from "@/lib/api";
import styles from "@/components/commerce.module.css";
import {
  PendingRegistrationList,
  RoleEditor,
  RoleList,
  UserEditor,
  UserList,
} from "./IdentityPanels";
import identityStyles from "./identity.module.css";
import {
  type AccountStatus,
  type Permission,
  type PendingRegistration,
  type Role,
  type RoleForm,
  type User,
  type UserDetail,
  type UserForm,
  type UserFormType,
} from "./identity-types";

function emptyUserForm(): UserForm {
  return {
    username: "",
    password: "",
    password_confirmation: "",
    email: "",
    full_name: "",
    role_ids: [],
    account_status: "active",
    must_change_password: true,
    business_name: "",
    slug: "",
    legal_name: "",
    contact_name: "",
    vendor_email: "",
    phone: "",
    vendor_status: "active",
    commission: 500,
  };
}

function formFromUser(user: UserDetail): UserForm {
  const vendor = user.vendor_profile;
  return {
    ...emptyUserForm(),
    username: user.username,
    email: user.email || "",
    full_name: user.full_name || "",
    role_ids: user.role_ids,
    account_status: user.account_status,
    must_change_password: user.must_change_password,
    business_name: vendor?.name || "",
    slug: vendor?.slug || "",
    legal_name: vendor?.legal_name || "",
    contact_name: vendor?.contact_name || "",
    vendor_email: vendor?.email || "",
    phone: vendor?.phone || "",
    vendor_status: vendor?.status || "active",
    commission: vendor?.default_commission_bps ?? 500,
  };
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function AdminIdentity() {
  const [activeTab, setActiveTab] = useState<"users" | "roles">("users");
  const [users, setUsers] = useState<User[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [pendingRegistrations, setPendingRegistrations] = useState<PendingRegistration[]>([]);
  const [pendingRoleIds, setPendingRoleIds] = useState<Record<string, string[]>>({});
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const formHeadingRef = useRef<HTMLHeadingElement>(null);
  const [showUserForm, setShowUserForm] = useState(false);
  const [userFormType, setUserFormType] = useState<UserFormType>("Generic");
  const [editingUser, setEditingUser] = useState<UserDetail | null>(null);
  const [userForm, setUserForm] = useState<UserForm>(emptyUserForm);
  const [showRoleForm, setShowRoleForm] = useState(false);
  const [editingRole, setEditingRole] = useState<Role | null>(null);
  const [roleForm, setRoleForm] = useState<RoleForm>({
    name: "",
    permissions: [],
  });

  async function refreshUsers() {
    setUsers((await fetchApi("/identity/users")) as User[]);
  }

  async function refreshPending() {
    setPendingLoading(true);
    try {
      const nextPending = (await fetchApi("/identity/registrations/pending")) as PendingRegistration[];
      setPendingRegistrations(nextPending);
      setPendingRoleIds((current) => {
        const next: Record<string, string[]> = {};
        for (const registration of nextPending) {
          next[registration.id] = current[registration.id] || registration.role_ids;
        }
        return next;
      });
    } catch (caught) {
      setError(errorMessage(caught, "Pending registrations could not be loaded."));
    } finally {
      setPendingLoading(false);
    }
  }

  useEffect(() => {
    Promise.all([
      fetchApi("/identity/users").catch(() => []),
      fetchApi("/identity/roles").catch(() => []),
      fetchApi("/identity/permissions").catch(() => []),
      fetchApi("/identity/registrations/pending").catch(() => []),
    ])
      .then(([nextUsers, nextRoles, nextPermissions, nextPending]) => {
        setUsers(nextUsers as User[]);
        setRoles(nextRoles as Role[]);
        setPermissions(nextPermissions as Permission[]);
        const registrations = nextPending as PendingRegistration[];
        setPendingRegistrations(registrations);
        setPendingRoleIds(
          Object.fromEntries(registrations.map((registration) => [registration.id, registration.role_ids])),
        );
      })
      .catch(() => setError("Data could not be loaded."))
      .finally(() => {
        setLoading(false);
        setPendingLoading(false);
      });
  }, []);

  useEffect(() => {
    if (showUserForm || showRoleForm) formHeadingRef.current?.focus();
  }, [showRoleForm, showUserForm]);

  function beginCreate(type: UserFormType) {
    setError("");
    setEditingUser(null);
    setUserFormType(type);
    setUserForm(emptyUserForm());
    setShowUserForm(true);
  }

  async function beginEdit(user: User) {
    setError("");
    try {
      const detail = (await fetchApi(
        `/identity/users/${user.id}`,
      )) as UserDetail;
      setEditingUser(detail);
      setUserFormType(detail.vendor_profile ? "Vendor" : "Generic");
      setUserForm(formFromUser(detail));
      setShowUserForm(true);
    } catch (caught) {
      setError(errorMessage(caught, "User details could not be loaded."));
    }
  }

  function closeUserForm() {
    setShowUserForm(false);
    setEditingUser(null);
    setUserForm(emptyUserForm());
  }

  async function submitUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    if (
      userForm.password &&
      userForm.password !== userForm.password_confirmation
    ) {
      setError("The new password and confirmation do not match.");
      return;
    }
    setSaving(true);
    try {
      if (editingUser) {
        const payload: Record<string, unknown> = {
          username: userForm.username,
          email: userForm.email || null,
          full_name: userForm.full_name || null,
          role_ids: userForm.role_ids,
          account_status: userForm.account_status,
          must_change_password: userForm.must_change_password,
        };
        if (userForm.password) payload.password = userForm.password;
        if (editingUser.vendor_profile) {
          payload.vendor_profile = {
            name: userForm.business_name,
            slug: userForm.slug || null,
            legal_name: userForm.legal_name || null,
            contact_name: userForm.contact_name || null,
            email: userForm.vendor_email || null,
            phone: userForm.phone || null,
            status: userForm.vendor_status,
            default_commission_bps: userForm.commission,
          };
        }
        await fetchApi(`/identity/users/${editingUser.id}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
      } else if (userFormType === "Vendor") {
        await fetchApi("/marketplace/vendors/with-account", {
          method: "POST",
          body: JSON.stringify({
            business_name: userForm.business_name,
            contact_name: userForm.contact_name,
            email: userForm.vendor_email || userForm.email || null,
            phone: userForm.phone || null,
            username: userForm.username,
            password: userForm.password,
            default_commission_bps: userForm.commission,
            use_activation: false,
          }),
        });
      } else {
        await fetchApi("/identity/users", {
          method: "POST",
          body: JSON.stringify({
            username: userForm.username,
            password: userForm.password,
            full_name: userForm.full_name || null,
            email: userForm.email || null,
            role_ids: userForm.role_ids,
            account_status: userForm.account_status,
            must_change_password: userForm.must_change_password,
          }),
        });
      }
      await refreshUsers();
      closeUserForm();
    } catch (caught) {
      setError(
        errorMessage(
          caught,
          editingUser ? "Failed to update user." : "Failed to create user.",
        ),
      );
    } finally {
      setSaving(false);
    }
  }

  async function submitRole(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSaving(true);
    try {
      if (editingRole)
        await fetchApi(`/identity/roles/${editingRole.id}`, {
          method: "PATCH",
          body: JSON.stringify({ permissions: roleForm.permissions }),
        });
      else
        await fetchApi("/identity/roles", {
          method: "POST",
          body: JSON.stringify(roleForm),
        });
      setRoles((await fetchApi("/identity/roles")) as Role[]);
      setShowRoleForm(false);
      setEditingRole(null);
    } catch (caught) {
      setError(errorMessage(caught, "Failed to save role."));
    } finally {
      setSaving(false);
    }
  }

  async function changeUserStatus(user: User, action: AccountStatus) {
    setError("");
    try {
      await fetchApi(`/identity/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({ account_status: action }),
      });
      await refreshUsers();
    } catch (caught) {
      setError(errorMessage(caught, "Failed to update user status."));
    }
  }

  function togglePendingRole(registration: PendingRegistration, roleId: string) {
    setPendingRoleIds((current) => {
      const selected = current[registration.id] || [];
      return {
        ...current,
        [registration.id]: selected.includes(roleId)
          ? selected.filter((id) => id !== roleId)
          : [...selected, roleId],
      };
    });
  }

  async function approvePending(registration: PendingRegistration) {
    setError("");
    setPendingActionId(registration.id);
    try {
      await fetchApi(`/identity/registrations/${registration.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ role_ids: pendingRoleIds[registration.id] || [] }),
      });
      await Promise.all([refreshUsers(), refreshPending()]);
    } catch (caught) {
      setError(errorMessage(caught, "Registration could not be approved."));
    } finally {
      setPendingActionId(null);
    }
  }

  async function rejectPending(registration: PendingRegistration) {
    setError("");
    setPendingActionId(registration.id);
    try {
      await fetchApi(`/identity/registrations/${registration.id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason: "Rejected by administrator." }),
      });
      await Promise.all([refreshUsers(), refreshPending()]);
    } catch (caught) {
      setError(errorMessage(caught, "Registration could not be rejected."));
    } finally {
      setPendingActionId(null);
    }
  }

  function toggleRole(roleId: string) {
    setUserForm((current) => ({
      ...current,
      role_ids: current.role_ids.includes(roleId)
        ? current.role_ids.filter((id) => id !== roleId)
        : [...current.role_ids, roleId],
    }));
  }

  function selectTab(tab: "users" | "roles") {
    setActiveTab(tab);
    setError("");
    setShowUserForm(false);
    setShowRoleForm(false);
  }

  function handleTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    const tabs: Array<"users" | "roles"> = ["users", "roles"];
    const index = tabs.indexOf(activeTab);
    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft")
      next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    selectTab(tabs[next]);
    document.getElementById(`identity-tab-${tabs[next]}`)?.focus();
  }

  function beginRoleEdit(role: Role) {
    setEditingRole(role);
    setRoleForm({ name: role.name, permissions: role.permissions });
    setShowRoleForm(true);
  }

  return (
    <>
      <div className={styles.pageHeader}>
        <div>
          <div className={styles.eyebrow}>Administration</div>
          <h1 className={styles.pageTitle}>Users &amp; Roles</h1>
          <p className={styles.pageSubtitle}>
            Manage system access, create vendors and staff accounts, and
            configure permissions.
          </p>
        </div>
        <div className={styles.headerActions}>
          {activeTab === "users" ? (
            <>
              <button
                className={styles.primaryButton}
                onClick={() => beginCreate("Vendor")}
              >
                Add Vendor User
              </button>
              <button
                className={styles.secondaryButton}
                onClick={() => beginCreate("Generic")}
              >
                Add Staff User
              </button>
            </>
          ) : (
            <button
              className={styles.primaryButton}
              onClick={() => {
                setEditingRole(null);
                setRoleForm({ name: "", permissions: [] });
                setShowRoleForm(true);
              }}
            >
              Create Custom Role
            </button>
          )}
        </div>
      </div>
      {error && (
        <div className={styles.error} role="alert">
          {error}
        </div>
      )}
      <div
        className={identityStyles.tabs}
        role="tablist"
        aria-label="Identity administration"
      >
        <button
          id="identity-tab-users"
          className={identityStyles.tab}
          type="button"
          role="tab"
          aria-selected={activeTab === "users"}
          aria-controls="identity-panel-users"
          tabIndex={activeTab === "users" ? 0 : -1}
          onClick={() => selectTab("users")}
          onKeyDown={handleTabKey}
        >
          Users
        </button>
        <button
          id="identity-tab-roles"
          className={identityStyles.tab}
          type="button"
          role="tab"
          aria-selected={activeTab === "roles"}
          aria-controls="identity-panel-roles"
          tabIndex={activeTab === "roles" ? 0 : -1}
          onClick={() => selectTab("roles")}
          onKeyDown={handleTabKey}
        >
          Roles
        </button>
      </div>
      {activeTab === "users" &&
        (showUserForm ? (
          <UserEditor
            form={userForm}
            formType={userFormType}
            editingUser={editingUser}
            roles={roles}
            saving={saving}
            headingRef={formHeadingRef}
            onChange={setUserForm}
            onToggleRole={toggleRole}
            onSubmit={submitUser}
            onCancel={closeUserForm}
          />
        ) : (
          <>
            <PendingRegistrationList
              registrations={pendingRegistrations}
              roles={roles}
              selectedRoleIds={pendingRoleIds}
              loading={pendingLoading}
              actionId={pendingActionId}
              onToggleRole={togglePendingRole}
              onApprove={(registration) => void approvePending(registration)}
              onReject={(registration) => void rejectPending(registration)}
            />
            <UserList
              users={users}
              loading={loading}
              onEdit={(user) => void beginEdit(user)}
              onChangeStatus={(user, status) =>
                void changeUserStatus(user, status)
              }
            />
          </>
        ))}
      {activeTab === "roles" &&
        (showRoleForm ? (
          <RoleEditor
            editingRole={editingRole}
            form={roleForm}
            permissions={permissions}
            saving={saving}
            headingRef={formHeadingRef}
            onChange={setRoleForm}
            onSubmit={submitRole}
            onCancel={() => {
              setShowRoleForm(false);
              setEditingRole(null);
            }}
          />
        ) : (
          <RoleList roles={roles} loading={loading} onEdit={beginRoleEdit} />
        ))}
    </>
  );
}
