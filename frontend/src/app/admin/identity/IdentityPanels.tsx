import type { FormEvent, Ref } from "react";
import { EmptyState, LoadingState } from "@/components/ui/Feedback";
import styles from "@/components/commerce.module.css";
import identityStyles from "./identity.module.css";
import {
  ACCOUNT_STATUSES,
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

type UserEditorProps = {
  form: UserForm;
  formType: UserFormType;
  editingUser: UserDetail | null;
  roles: Role[];
  saving: boolean;
  headingRef: Ref<HTMLHeadingElement>;
  onChange: (form: UserForm) => void;
  onToggleRole: (roleId: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
};

export function UserEditor({
  form,
  formType,
  editingUser,
  roles,
  saving,
  headingRef,
  onChange,
  onToggleRole,
  onSubmit,
  onCancel,
}: UserEditorProps) {
  const update = <K extends keyof UserForm>(key: K, value: UserForm[K]) =>
    onChange({ ...form, [key]: value });
  const showVendorProfile =
    formType === "Vendor" &&
    (Boolean(editingUser?.vendor_profile) || !editingUser);

  return (
    <section
      id="identity-panel-users"
      className={styles.panel}
      role="tabpanel"
      aria-labelledby="identity-tab-users"
    >
      <h2
        className={identityStyles.sectionTitle}
        ref={headingRef}
        tabIndex={-1}
      >
        {editingUser ? `Edit ${formType} User` : `Create ${formType} User`}
      </h2>
      <form
        className={identityStyles.form}
        onSubmit={onSubmit}
        aria-busy={saving}
      >
        <label className={styles.field}>
          <span>Username (Login ID)</span>
          <input
            type="text"
            value={form.username}
            onChange={(event) => update("username", event.target.value)}
            required
            minLength={3}
            pattern="[A-Za-z0-9_.-]+"
            autoComplete="username"
          />
        </label>
        <label className={styles.field}>
          <span>{editingUser ? "New Password (optional)" : "Password"}</span>
          <input
            type="password"
            value={form.password}
            onChange={(event) => update("password", event.target.value)}
            required={!editingUser}
            minLength={8}
            autoComplete="new-password"
          />
        </label>
        {(form.password || !editingUser) && (
          <label className={styles.field}>
            <span>Confirm Password</span>
            <input
              type="password"
              value={form.password_confirmation}
              onChange={(event) =>
                update("password_confirmation", event.target.value)
              }
              required={!editingUser || Boolean(form.password)}
              minLength={8}
              autoComplete="new-password"
            />
          </label>
        )}
        <label className={styles.field}>
          <span>Account Email</span>
          <input
            type="email"
            value={form.email}
            onChange={(event) => update("email", event.target.value)}
            required={!editingUser && formType === "Vendor"}
            autoComplete="email"
          />
        </label>
        <label className={styles.field}>
          <span>Full Name</span>
          <input
            type="text"
            value={form.full_name}
            onChange={(event) => update("full_name", event.target.value)}
            autoComplete="name"
          />
        </label>
        <label className={styles.field}>
          <span>Account Status</span>
          <select
            value={form.account_status}
            onChange={(event) =>
              update("account_status", event.target.value as AccountStatus)
            }
          >
            {ACCOUNT_STATUSES.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </select>
        </label>
        <label className={identityStyles.checkboxRow}>
          <input
            type="checkbox"
            checked={form.must_change_password}
            onChange={(event) =>
              update("must_change_password", event.target.checked)
            }
          />
          Require password change on next login
        </label>

        <fieldset className={identityStyles.fieldset}>
          <legend>Roles</legend>
          <div className={identityStyles.roleGrid}>
            {roles.map((role) => (
              <label key={role.id} className={identityStyles.checkboxRow}>
                <input
                  type="checkbox"
                  checked={form.role_ids.includes(role.id)}
                  onChange={() => onToggleRole(role.id)}
                />
                {role.name}
              </label>
            ))}
          </div>
        </fieldset>

        {showVendorProfile && (
          <fieldset
            className={`${identityStyles.fieldset} ${identityStyles.vendorGrid}`}
          >
            <legend>Vendor Profile</legend>
            <label className={styles.field}>
              <span>Business Name</span>
              <input
                type="text"
                value={form.business_name}
                onChange={(event) =>
                  update("business_name", event.target.value)
                }
                required
                autoComplete="organization"
              />
            </label>
            {editingUser && (
              <label className={styles.field}>
                <span>Slug</span>
                <input
                  type="text"
                  value={form.slug}
                  onChange={(event) => update("slug", event.target.value)}
                  required
                />
              </label>
            )}
            {editingUser && (
              <label className={styles.field}>
                <span>Legal Name</span>
                <input
                  type="text"
                  value={form.legal_name}
                  onChange={(event) => update("legal_name", event.target.value)}
                />
              </label>
            )}
            <label className={styles.field}>
              <span>Contact Name</span>
              <input
                type="text"
                value={form.contact_name}
                onChange={(event) => update("contact_name", event.target.value)}
                autoComplete="name"
              />
            </label>
            <label className={styles.field}>
              <span>Vendor Email</span>
              <input
                type="email"
                value={form.vendor_email}
                onChange={(event) => update("vendor_email", event.target.value)}
                autoComplete="email"
              />
            </label>
            <label className={styles.field}>
              <span>Phone</span>
              <input
                type="tel"
                value={form.phone}
                onChange={(event) => update("phone", event.target.value)}
                autoComplete="tel"
              />
            </label>
            {editingUser && (
              <label className={styles.field}>
                <span>Vendor Status</span>
                <select
                  value={form.vendor_status}
                  onChange={(event) =>
                    update("vendor_status", event.target.value)
                  }
                >
                  {ACCOUNT_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {status}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label className={styles.field}>
              <span>Commission (BPS)</span>
              <input
                type="number"
                min={0}
                max={10000}
                value={form.commission}
                onChange={(event) =>
                  update(
                    "commission",
                    Number.parseInt(event.target.value, 10) || 0,
                  )
                }
              />
            </label>
          </fieldset>
        )}

        <div className={styles.formActions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={saving}
          >
            {saving ? "Saving…" : editingUser ? "Save Changes" : "Create User"}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={onCancel}
            disabled={saving}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

export function UserList({
  users,
  loading,
  onEdit,
  onChangeStatus,
}: {
  users: User[];
  loading: boolean;
  onEdit: (user: User) => void;
  onChangeStatus: (user: User, status: AccountStatus) => void;
}) {
  return (
    <section
      id="identity-panel-users"
      className={styles.panel}
      role="tabpanel"
      aria-labelledby="identity-tab-users"
    >
      {loading ? (
        <LoadingState label="Loading users" />
      ) : users.length === 0 ? (
        <EmptyState
          title="No users yet"
          description="Create a staff or vendor account to get started."
        />
      ) : (
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.mobileCardTable}`}>
            <caption className={styles.srOnly}>
              Users, assigned roles, account status, and available actions
            </caption>
            <thead>
              <tr>
                <th>Username</th>
                <th>Roles</th>
                <th>Status</th>
                <th>Must Change Pwd</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.id}>
                  <td data-label="Username">
                    <strong>{user.username}</strong>
                  </td>
                  <td data-label="Roles">
                    {user.role_names.join(", ") || "—"}
                  </td>
                  <td data-label="Status">
                    <span
                      className={`${styles.badge} ${user.account_status === "active" ? styles.badgeSuccess : styles.badgeWarning}`}
                    >
                      {user.account_status}
                    </span>
                  </td>
                  <td data-label="Password change">
                    {user.must_change_password ? "Yes" : "No"}
                  </td>
                  <td data-label="Actions">
                    <div className={styles.toolbarActions}>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={() => onEdit(user)}
                      >
                        Edit
                      </button>
                      {user.account_status !== "active" && (
                        <button
                          type="button"
                          className={styles.primaryButton}
                          onClick={() => onChangeStatus(user, "active")}
                        >
                          Activate
                        </button>
                      )}
                      {user.account_status === "active" && (
                        <button
                          type="button"
                          className={styles.secondaryButton}
                          onClick={() => onChangeStatus(user, "paused")}
                        >
                          Pause
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function PendingRegistrationList({
  registrations,
  roles,
  selectedRoleIds,
  loading,
  actionId,
  onToggleRole,
  onApprove,
  onReject,
}: {
  registrations: PendingRegistration[];
  roles: Role[];
  selectedRoleIds: Record<string, string[]>;
  loading: boolean;
  actionId: string | null;
  onToggleRole: (registration: PendingRegistration, roleId: string) => void;
  onApprove: (registration: PendingRegistration) => void;
  onReject: (registration: PendingRegistration) => void;
}) {
  return (
    <section className={styles.panel} aria-labelledby="pending-registrations-title">
      <div className={identityStyles.queueHeader}>
        <div>
          <div className={styles.eyebrow}>Approval queue</div>
          <h2 id="pending-registrations-title" className={identityStyles.sectionTitle}>
            Pending registrations
          </h2>
        </div>
        <span className={`${styles.badge} ${styles.badgeWarning}`}>
          {loading ? "Loading" : `${registrations.length} awaiting review`}
        </span>
      </div>
      {loading ? (
        <LoadingState label="Loading pending registrations" />
      ) : registrations.length === 0 ? (
        <EmptyState
          title="No pending registrations"
          description="New staff and vendor requests will appear here for review."
        />
      ) : (
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.mobileCardTable}`}>
          <caption className={styles.srOnly}>
            Public registration requests awaiting administrator approval
          </caption>
          <thead>
            <tr>
              <th>Type</th>
              <th>Applicant</th>
              <th>Vendor details</th>
              <th>Assign roles</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {registrations.map((registration) => {
              const selected = selectedRoleIds[registration.id] || [];
              const vendor = registration.vendor_profile;
              const busy = actionId === registration.id;
              return (
                <tr key={registration.id}>
                  <td data-label="Type">
                    <span className={`${styles.badge} ${styles.badgeWarning}`}>
                      {registration.registration_type}
                    </span>
                  </td>
                  <td data-label="Applicant">
                    <strong>{registration.username}</strong>
                    <div className={styles.muted}>{registration.email || "No email"}</div>
                    {registration.full_name && <div className={styles.muted}>{registration.full_name}</div>}
                  </td>
                  <td data-label="Vendor details">
                    {vendor ? (
                      <>
                        <strong>{vendor.name}</strong>
                        {vendor.contact_name && <div className={styles.muted}>{vendor.contact_name}</div>}
                        {(vendor.email || vendor.phone) && (
                          <div className={styles.muted}>{[vendor.email, vendor.phone].filter(Boolean).join(" · ")}</div>
                        )}
                      </>
                    ) : "—"}
                  </td>
                  <td data-label="Assign roles">
                    <div className={identityStyles.roleGrid}>
                      {roles.map((role) => {
                        const isVendorRole = registration.registration_type === "vendor" && role.name === "Vendor";
                        return (
                          <label key={role.id} className={identityStyles.checkboxRow}>
                            <input
                              type="checkbox"
                              checked={selected.includes(role.id)}
                              disabled={busy || isVendorRole}
                              onChange={() => onToggleRole(registration, role.id)}
                            />
                            {role.name}
                          </label>
                        );
                      })}
                    </div>
                  </td>
                  <td data-label="Actions">
                    <div className={styles.toolbarActions}>
                      <button type="button" className={styles.primaryButton} disabled={busy} onClick={() => onApprove(registration)}>
                        {busy ? "Saving..." : "Approve"}
                      </button>
                      <button type="button" className={styles.secondaryButton} disabled={busy} onClick={() => onReject(registration)}>
                        Reject
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
            </tbody>
          </table>
        </div>
      )}
      {registrations.length > 0 && (
        <p className={styles.muted}>
          Staff requests require at least one role. Vendor requests always retain the restricted Vendor role.
        </p>
      )}
    </section>
  );
}

type RoleEditorProps = {
  editingRole: Role | null;
  form: RoleForm;
  permissions: Permission[];
  saving: boolean;
  headingRef: Ref<HTMLHeadingElement>;
  onChange: (form: RoleForm) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onCancel: () => void;
};

export function RoleEditor({
  editingRole,
  form,
  permissions,
  saving,
  headingRef,
  onChange,
  onSubmit,
  onCancel,
}: RoleEditorProps) {
  return (
    <section
      id="identity-panel-roles"
      className={styles.panel}
      role="tabpanel"
      aria-labelledby="identity-tab-roles"
    >
      <h2
        className={identityStyles.sectionTitle}
        ref={headingRef}
        tabIndex={-1}
      >
        {editingRole ? `Edit Role: ${editingRole.name}` : "Create Custom Role"}
      </h2>
      {editingRole && !editingRole.is_custom && (
        <div className={identityStyles.warning} role="alert">
          <strong>System role:</strong> Changes affect every account assigned to{" "}
          {editingRole.name}.
        </div>
      )}
      <form
        className={identityStyles.roleForm}
        onSubmit={onSubmit}
        aria-busy={saving}
      >
        {!editingRole && (
          <label className={`${styles.field} ${identityStyles.roleName}`}>
            <span>Role Name</span>
            <input
              type="text"
              value={form.name}
              onChange={(event) =>
                onChange({ ...form, name: event.target.value })
              }
              required
            />
          </label>
        )}
        <fieldset className={identityStyles.permissionFieldset}>
          <legend>Permissions</legend>
          <p className={styles.muted}>
            Select only the capabilities this role needs. Backend permission
            checks remain authoritative.
          </p>
          <div className={identityStyles.permissionsGrid}>
            {permissions.map((permission) => {
              const selected = form.permissions.includes(permission.id);
              return (
                <label
                  key={permission.id}
                  className={`${identityStyles.permissionChoice} ${selected ? identityStyles.permissionChoiceSelected : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={selected}
                    onChange={(event) =>
                      onChange({
                        ...form,
                        permissions: event.target.checked
                          ? [...form.permissions, permission.id]
                          : form.permissions.filter(
                              (id) => id !== permission.id,
                            ),
                      })
                    }
                  />
                  <span>
                    <strong>{permission.id}</strong>
                    <small>{permission.description}</small>
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
        <div className={styles.formActions}>
          <button
            type="submit"
            className={styles.primaryButton}
            disabled={saving}
          >
            {saving ? "Saving…" : "Save Role"}
          </button>
          <button
            type="button"
            className={styles.secondaryButton}
            disabled={saving}
            onClick={onCancel}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

export function RoleList({
  roles,
  loading,
  onEdit,
}: {
  roles: Role[];
  loading: boolean;
  onEdit: (role: Role) => void;
}) {
  return (
    <section
      id="identity-panel-roles"
      className={styles.panel}
      role="tabpanel"
      aria-labelledby="identity-tab-roles"
    >
      {loading ? (
        <LoadingState label="Loading roles" />
      ) : roles.length === 0 ? (
        <EmptyState
          title="No roles found"
          description="Create a custom role to define a permission set."
        />
      ) : (
        <div className={styles.tableWrap}>
          <table className={`${styles.table} ${styles.mobileCardTable}`}>
            <caption className={styles.srOnly}>
              Roles, types, permission counts, and available actions
            </caption>
            <thead>
              <tr>
                <th>Role Name</th>
                <th>Type</th>
                <th>Permissions Count</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {roles.map((role) => (
                <tr key={role.id}>
                  <td data-label="Role">
                    <strong>{role.name}</strong>
                  </td>
                  <td data-label="Type">
                    {role.is_custom ? "Custom" : "System Default"}
                  </td>
                  <td data-label="Permissions">{role.permissions.length}</td>
                  <td data-label="Actions">
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      onClick={() => onEdit(role)}
                    >
                      Edit Permissions
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
