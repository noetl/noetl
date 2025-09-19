# Validation: Grammar (EBNF)

These fragments capture the credential-related clauses in the playbook DSL.

```
auth_clause        = "auth" ":" identifier ;

credentials_clause = "credentials" ":" "{" credential_binding { "," credential_binding } "}" ;

credential_binding = alias ":" "{" "key" ":" identifier "}" ;

alias              = identifier ;
identifier         = ? YAML scalar string (restricted to [A-Za-z0-9_\-]) ? ;
```

Secret references appear inside templates and are not a top-level clause:

```
{{ secret.<identifier> }}
```

