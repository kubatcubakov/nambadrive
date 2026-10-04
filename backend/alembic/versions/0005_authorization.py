"""ACL, roles, hard policy and scoped audited emergency grants."""

from alembic import op

revision = "0005_authorization"
down_revision = "0004_resources"
branch_labels = None
depends_on = None

POSTGRES_SQL = [
    (
        "\nCREATE TABLE roles (\n\tid UUID NOT NULL, \n\tname VARCHAR(32) NOT N"
        "ULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (name)\n)\n\n"
    ),
    ("\nCREATE TABLE permissions (\n\tid VARCHAR(40) NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"),
    (
        "\nCREATE TABLE role_permissions (\n\trole_id UUID NOT NULL, \n\tpermis"
        "sion_id VARCHAR(40) NOT NULL, \n\tPRIMARY KEY (role_id, permission_"
        "id), \n\tFOREIGN KEY(role_id) REFERENCES roles (id), \n\tFOREIGN KEY("
        "permission_id) REFERENCES permissions (id)\n)\n\n"
    ),
    (
        "\nCREATE TABLE role_bindings (\n\tid UUID NOT NULL, \n\tuser_id UUID N"
        "OT NULL, \n\trole_id UUID NOT NULL, \n\tresource_id UUID, \n\tvalid_fro"
        "m TIMESTAMP WITH TIME ZONE NOT NULL, \n\tvalid_until TIMESTAMP WITH"
        " TIME ZONE, \n\trevoked_at TIMESTAMP WITH TIME ZONE, \n\tPRIMARY KEY "
        "(id), \n\tCHECK (valid_until IS NULL OR valid_until > valid_from), "
        "\n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(role_"
        "id) REFERENCES roles (id), \n\tFOREIGN KEY(resource_id) REFERENCES "
        "resources (id)\n)\n\n"
    ),
    (
        "\nCREATE TABLE acl_entries (\n\tid UUID NOT NULL, \n\tresource_id UUID"
        " NOT NULL, \n\tprincipal_type VARCHAR(16) NOT NULL, \n\tprincipal_id "
        "UUID NOT NULL, \n\tpermission_id VARCHAR(40) NOT NULL, \n\teffect VAR"
        "CHAR(8) NOT NULL, \n\tapplies_to_self BOOLEAN DEFAULT 'true' NOT NU"
        "LL, \n\tpropagate_to_children BOOLEAN DEFAULT 'false' NOT NULL, \n\tv"
        "alid_from TIMESTAMP WITH TIME ZONE NOT NULL, \n\tvalid_until TIMEST"
        "AMP WITH TIME ZONE, \n\tsource VARCHAR(32) DEFAULT 'EXPLICIT' NOT N"
        "ULL, \n\tcreated_by UUID NOT NULL, \n\trevoked_at TIMESTAMP WITH TIME"
        " ZONE, \n\treason TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (princ"
        "ipal_type IN ('USER','DEPARTMENT','ROLE')), \n\tCHECK (effect IN ('"
        "ALLOW','DENY')), \n\tCHECK (valid_until IS NULL OR valid_until > va"
        "lid_from), \n\tCHECK (applies_to_self OR propagate_to_children), \n\t"
        "FOREIGN KEY(resource_id) REFERENCES resources (id), \n\tFOREIGN KEY"
        "(permission_id) REFERENCES permissions (id), \n\tFOREIGN KEY(create"
        "d_by) REFERENCES users (id)\n)\n\n"
    ),
    (
        "\nCREATE TABLE hard_policies (\n\tid UUID NOT NULL, \n\tresource_id UU"
        "ID, \n\tpermission_id VARCHAR(40) NOT NULL, \n\treason TEXT NOT NULL,"
        " \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(resource_id) REFERENCES resour"
        "ces (id), \n\tFOREIGN KEY(permission_id) REFERENCES permissions (id"
        ")\n)\n\n"
    ),
    (
        "\nCREATE TABLE break_glass_grants (\n\tid UUID NOT NULL, \n\tuser_id U"
        "UID NOT NULL, \n\tresource_id UUID NOT NULL, \n\tpermission_id VARCHA"
        "R(40) NOT NULL, \n\tvalid_from TIMESTAMP WITH TIME ZONE NOT NULL, \n"
        "\tvalid_until TIMESTAMP WITH TIME ZONE NOT NULL, \n\trevoked_at TIME"
        "STAMP WITH TIME ZONE, \n\treason TEXT NOT NULL, \n\tcreated_by UUID N"
        "OT NULL, \n\taudited BOOLEAN DEFAULT 'false' NOT NULL, \n\tPRIMARY KE"
        "Y (id), \n\tCHECK (valid_until > valid_from), \n\tCHECK (length(reaso"
        "n) > 0), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\tFOREIGN "
        "KEY(resource_id) REFERENCES resources (id), \n\tFOREIGN KEY(permiss"
        "ion_id) REFERENCES permissions (id), \n\tFOREIGN KEY(created_by) RE"
        "FERENCES users (id)\n)\n\n"
    ),
    ("CREATE INDEX ix_role_bindings_user_id ON role_bindings (user_id)"),
    ("CREATE INDEX ix_role_bindings_resource_id ON role_bindings (resource_id)"),
    ("CREATE INDEX ix_acl_entries_resource_id ON acl_entries (resource_id)"),
    ("CREATE INDEX ix_break_glass_grants_user_id ON break_glass_grants (user_id)"),
]

SQLITE_SQL = [
    (
        "\nCREATE TABLE roles (\n\tid CHAR(32) NOT NULL, \n\tname VARCHAR("
        "32) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (name)\n)\n\n"
    ),
    ("\nCREATE TABLE permissions (\n\tid VARCHAR(40) NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"),
    (
        "\nCREATE TABLE role_permissions (\n\trole_id CHAR(32) NOT NULL,"
        " \n\tpermission_id VARCHAR(40) NOT NULL, \n\tPRIMARY KEY (role_i"
        "d, permission_id), \n\tFOREIGN KEY(role_id) REFERENCES roles ("
        "id), \n\tFOREIGN KEY(permission_id) REFERENCES permissions (id"
        ")\n)\n\n"
    ),
    (
        "\nCREATE TABLE role_bindings (\n\tid CHAR(32) NOT NULL, \n\tuser_"
        "id CHAR(32) NOT NULL, \n\trole_id CHAR(32) NOT NULL, \n\tresourc"
        "e_id CHAR(32), \n\tvalid_from DATETIME NOT NULL, \n\tvalid_until"
        " DATETIME, \n\trevoked_at DATETIME, \n\tPRIMARY KEY (id), \n\tCHEC"
        "K (valid_until IS NULL OR valid_until > valid_from), \n\tFOREI"
        "GN KEY(user_id) REFERENCES users (id), \n\tFOREIGN KEY(role_id"
        ") REFERENCES roles (id), \n\tFOREIGN KEY(resource_id) REFERENC"
        "ES resources (id)\n)\n\n"
    ),
    (
        "\nCREATE TABLE acl_entries (\n\tid CHAR(32) NOT NULL, \n\tresourc"
        "e_id CHAR(32) NOT NULL, \n\tprincipal_type VARCHAR(16) NOT NUL"
        "L, \n\tprincipal_id CHAR(32) NOT NULL, \n\tpermission_id VARCHAR"
        "(40) NOT NULL, \n\teffect VARCHAR(8) NOT NULL, \n\tapplies_to_se"
        "lf BOOLEAN DEFAULT 'true' NOT NULL, \n\tpropagate_to_children "
        "BOOLEAN DEFAULT 'false' NOT NULL, \n\tvalid_from DATETIME NOT "
        "NULL, \n\tvalid_until DATETIME, \n\tsource VARCHAR(32) DEFAULT '"
        "EXPLICIT' NOT NULL, \n\tcreated_by CHAR(32) NOT NULL, \n\trevoke"
        "d_at DATETIME, \n\treason TEXT NOT NULL, \n\tPRIMARY KEY (id), \n"
        "\tCHECK (principal_type IN ('USER','DEPARTMENT','ROLE')), \n\tC"
        "HECK (effect IN ('ALLOW','DENY')), \n\tCHECK (valid_until IS N"
        "ULL OR valid_until > valid_from), \n\tCHECK (applies_to_self O"
        "R propagate_to_children), \n\tFOREIGN KEY(resource_id) REFEREN"
        "CES resources (id), \n\tFOREIGN KEY(permission_id) REFERENCES "
        "permissions (id), \n\tFOREIGN KEY(created_by) REFERENCES users"
        " (id)\n)\n\n"
    ),
    (
        "\nCREATE TABLE hard_policies (\n\tid CHAR(32) NOT NULL, \n\tresou"
        "rce_id CHAR(32), \n\tpermission_id VARCHAR(40) NOT NULL, \n\trea"
        "son TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(resourc"
        "e_id) REFERENCES resources (id), \n\tFOREIGN KEY(permission_id"
        ") REFERENCES permissions (id)\n)\n\n"
    ),
    (
        "\nCREATE TABLE break_glass_grants (\n\tid CHAR(32) NOT NULL, \n\t"
        "user_id CHAR(32) NOT NULL, \n\tresource_id CHAR(32) NOT NULL, "
        "\n\tpermission_id VARCHAR(40) NOT NULL, \n\tvalid_from DATETIME "
        "NOT NULL, \n\tvalid_until DATETIME NOT NULL, \n\trevoked_at DATE"
        "TIME, \n\treason TEXT NOT NULL, \n\tcreated_by CHAR(32) NOT NULL"
        ", \n\taudited BOOLEAN DEFAULT 'false' NOT NULL, \n\tPRIMARY KEY "
        "(id), \n\tCHECK (valid_until > valid_from), \n\tCHECK (length(re"
        "ason) > 0), \n\tFOREIGN KEY(user_id) REFERENCES users (id), \n\t"
        "FOREIGN KEY(resource_id) REFERENCES resources (id), \n\tFOREIG"
        "N KEY(permission_id) REFERENCES permissions (id), \n\tFOREIGN "
        "KEY(created_by) REFERENCES users (id)\n)\n\n"
    ),
    ("CREATE INDEX ix_role_bindings_resource_id ON role_bindings (resource_id)"),
    ("CREATE INDEX ix_role_bindings_user_id ON role_bindings (user_id)"),
    ("CREATE INDEX ix_acl_entries_resource_id ON acl_entries (resource_id)"),
    ("CREATE INDEX ix_break_glass_grants_user_id ON break_glass_grants (user_id)"),
]

SEED_SQL = [
    ("INSERT INTO permissions (id) VALUES ('CHANGE_ACL')"),
    ("INSERT INTO permissions (id) VALUES ('CLIPBOARD_COPY')"),
    ("INSERT INTO permissions (id) VALUES ('COPY')"),
    ("INSERT INTO permissions (id) VALUES ('CREATE')"),
    ("INSERT INTO permissions (id) VALUES ('CREATE_FOLDER')"),
    ("INSERT INTO permissions (id) VALUES ('CREATE_SPACE')"),
    ("INSERT INTO permissions (id) VALUES ('DELETE')"),
    ("INSERT INTO permissions (id) VALUES ('DOWNLOAD')"),
    ("INSERT INTO permissions (id) VALUES ('EDIT')"),
    ("INSERT INTO permissions (id) VALUES ('EXPORT_PDF')"),
    ("INSERT INTO permissions (id) VALUES ('EXTERNAL_SHARE')"),
    ("INSERT INTO permissions (id) VALUES ('MOVE')"),
    ("INSERT INTO permissions (id) VALUES ('PREVIEW')"),
    ("INSERT INTO permissions (id) VALUES ('PRINT')"),
    ("INSERT INTO permissions (id) VALUES ('PURGE')"),
    ("INSERT INTO permissions (id) VALUES ('RENAME')"),
    ("INSERT INTO permissions (id) VALUES ('REQUEST_ACCESS_DISCOVERY')"),
    ("INSERT INTO permissions (id) VALUES ('RESTORE_VERSION')"),
    ("INSERT INTO permissions (id) VALUES ('SHARE')"),
    ("INSERT INTO permissions (id) VALUES ('UPLOAD_NEW_VERSION')"),
    ("INSERT INTO permissions (id) VALUES ('VIEW')"),
    ("INSERT INTO permissions (id) VALUES ('VIEW_VERSION_HISTORY')"),
    ("INSERT INTO roles (id,name) VALUES ('99d37c5862e75333af0eb1de5142a4d8','SYSTEM_ADMIN')"),
    ("INSERT INTO roles (id,name) VALUES ('f273d8819f8e596b9f080d1a5ec9e5c8','STORAGE_ADMIN')"),
    ("INSERT INTO roles (id,name) VALUES ('8eeb4d48f9715cf191a16410b6c4f6e1','SECURITY_ADMIN')"),
    ("INSERT INTO roles (id,name) VALUES ('58f8caf8edf8528081d0c549547dab60','SPACE_OWNER')"),
    ("INSERT INTO roles (id,name) VALUES ('deafd6b11894512ba9e4e6bfd1193c1a','FOLDER_OWNER')"),
    ("INSERT INTO roles (id,name) VALUES ('5b76f06e6b83587c94566b77df8e887f','DOCUMENT_OWNER')"),
    ("INSERT INTO roles (id,name) VALUES ('cfb42eca9a975a20ba5b0c1085533c00','EDITOR')"),
    ("INSERT INTO roles (id,name) VALUES ('0f25975d5e295c9287c064765e8f923d','REVIEWER')"),
    ("INSERT INTO roles (id,name) VALUES ('967f7479a5a8597b8ba488bba00fa9e4','READER')"),
    ("INSERT INTO roles (id,name) VALUES ('3f273aab94545bee86c05007c2969343','GUEST')"),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('cfb"
        "42eca9a975a20ba5b0c1085533c00','EDIT')"
    ),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('cfb"
        "42eca9a975a20ba5b0c1085533c00','PREVIEW')"
    ),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('cfb"
        "42eca9a975a20ba5b0c1085533c00','UPLOAD_NEW_VERSION')"
    ),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('cfb"
        "42eca9a975a20ba5b0c1085533c00','VIEW')"
    ),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('0f2"
        "5975d5e295c9287c064765e8f923d','PREVIEW')"
    ),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('0f2"
        "5975d5e295c9287c064765e8f923d','VIEW')"
    ),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('967"
        "f7479a5a8597b8ba488bba00fa9e4','PREVIEW')"
    ),
    (
        "INSERT INTO role_permissions (role_id,permission_id) VALUES ('967"
        "f7479a5a8597b8ba488bba00fa9e4','VIEW')"
    ),
]


def upgrade() -> None:
    statements = POSTGRES_SQL if op.get_context().dialect.name == "postgresql" else SQLITE_SQL
    for statement in statements + SEED_SQL:
        op.execute(statement)
    if op.get_context().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE break_glass_grants ADD CONSTRAINT break_glass_max_hour "
            "CHECK (valid_until <= valid_from + interval '1 hour')"
        )


def downgrade() -> None:
    for table in [
        "break_glass_grants",
        "hard_policies",
        "acl_entries",
        "role_bindings",
        "role_permissions",
        "permissions",
        "roles",
    ]:
        op.drop_table(table)
