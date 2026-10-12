# instance.json reference

Each instance has one `instance.json` at its root.
The installer writes it from the answers of the interview, and an overlay effort changes it later.
Every key except `effortkit`, `name` and `repo` has a default, so an answers file holds only the keys that differ.
`effortkit check <instance>` validates the file and renders every prompt and agent config in memory.

## Keys

| Key | Default | Meaning |
|---|---|---|
| `effortkit` | `1` | The schema version. The installer sets it. |
| `name` | the folder name | The instance name: 3 to 50 lowercase letters, digits and `-`. It names the tmux socket and appears in the prompts. |
| `description` | `""` | One sentence on the project. The prompts and the project steering use it. |
| `repo.url` | none | A clone source. The installer makes a bare clone in `product.git`. |
| `repo.path` | none | An existing clone to use instead of a bare clone. Efforts add worktrees to it. Give `url` or `path`. |
| `repo.remote` | `origin` | The remote that `effort new` fetches. |
| `repo.default_base` | detected | The base of a new effort, for example `origin/main`. The installer reads it from the remote HEAD. |
| `ticket.regex` | none | The format of a ticket key, for example `^PROJ-\d+$`. `effort new --ticket` checks it. |
| `ticket.example` | none | One valid key, for the prompts. |
| `branch.template` | `{ticket}/{name}` | The branch of a new effort with a ticket. |
| `branch.fallback` | `effort/{name}` | The branch of a new effort without a ticket. |
| `commit.subject_regex` | `^\S` | The rule for a commit subject. The gate and the commit-msg hook check it. |
| `commit.subject_help` | `<a short subject>` | A template of a good subject, for the prompts and the refusals, for example `PROJ-NNN: <subject>`. |
| `commit.forbid_coauthor` | `true` | Refuse a `Co-authored-by` line. |
| `commit.forbid_dashes` | `false` | Refuse an em dash or an en dash in a commit message. |
| `push.protected_branches` | `["main", "master"]` | The pre-push hook refuses a push to these branches. Agents never push at all. |
| `push.max_tags` | `2` | The pre-push hook refuses a push with more tags. |
| `tests.commands` | `[]` | The test commands, as the prompts show them. `<placeholder>` parts are allowed. |
| `tests.patterns` | `[]` | Full-match regexes over the words of one command, joined by single spaces. A matching command needs no approval, and the reviewer and the debugger may run it. Every entry of `tests.commands` must match one pattern, with each placeholder read as `x`. |
| `tester_globs` | common test folders | The files that the tester may change, as globs relative to the tree root. |
| `forbidden_commands` | `[]` | `{"pattern", "reason", "fix"}` entries. The gate refuses a command whose words match `pattern` for every role, also after the approval. |
| `build_dirs` | build output names | Folder names where `rm -r` is allowed. |
| `tree_excludes` | `[]` | Lines for `info/exclude` of the repository, for files that every tree creates. |
| `tree_setup` | `[]` | Shell commands that `effort new` runs in a new tree of the project, for example `npm ci`. The owner wrote them, so no gate judges them. |
| `secrets.files`, `secrets.dirs`, `secrets.names` | `[]` | More credential paths and file names, on top of the built-in list (`~/.ssh`, `~/.git-credentials`, `.env` and others). |
| `max_efforts` | `8` | The limit of open efforts with a tree. |
| `models.default` | `claude-opus-5.5` | The model of every role without its own entry. |
| `models.<role>` | sonnet for tester and reviewer | The model of one role. |
| `mcp.<role>` | `[]` | MCP tools of one role, for example `["@mcp-web-search"]`. A listed role loads `~/.kiro/settings/mcp.json`. |
| `extra_skills.<role>` | `[]` | More `SKILL.md` paths or globs for one role, for example a skill in `~/.kiro/skills`. |
| `roles.<name>` | the built-in roles | A custom role, or a change to a built-in one: `profile`, `description`, `artifact`, `model`, `web`, `tree_globs`, `resources`. A custom role needs its prompt in `overlay/agents/<name>.md`. `null` switches a built-in role off. |
| `kinds.<name>` | the built-in kinds | A custom kind: `repo` (`product`, `kit`, `instance` or `null`), `lane` (a skill name), `stage`, `about`, `detached`, `base`. |
| `improve.trigger` | `on-close` | `on-close`: `effort close` starts an improvement round when the open reports reach the threshold. `manual`: only `effort improve` starts one. |
| `improve.threshold` | `3` | The number of open reports that starts a round on close. |
| `settings` | `{}` | More kiro-cli settings for `.kiro/settings/cli.json`. |
| `forge.host` | none | The GitLab or GitHub host, for `glab` and `gh` in the sessions. |

## Profiles

| Profile | Shell | Tree | Approval |
|---|---|---|---|
| `writer` | trusted | the whole tree | needed for a change |
| `test-writer` | trusted | `tester_globs` or the role's `tree_globs` | needed for a change |
| `reader` | read-only allowlist | none | - |
| `reader+tests` | read-only allowlist and `tests.patterns` | none | - |
| `noshell` | none | none | - |

The built-in roles: explorer, researcher and improver are `reader`; reviewer and debugger are `reader+tests`; planner is `noshell`; developer is `writer`; tester is `test-writer`.
The supervisor has its own profile.

## Overlay

| Path | Use |
|---|---|
| `overlay/steering/*.md` | Project steering for every role: what the project is, its layout, build, tests, conventions and traps. |
| `overlay/agents/<role>.md` | Project rules for one role. The generator appends the file to the kit prompt of the role. The prompt of a custom role is this file alone. |
| `overlay/skills/<name>/SKILL.md` | Project skills for every role, and the lane skills of custom kinds. |

Prompts, steering and overlay files may use these placeholders: `{{project}}`, `{{description}}`, `{{instance}}`, `{{kit}}`, `{{plan}}`, `{{knowledge}}`, `{{knowledge_inbox}}`, `{{reports}}`, `{{reference}}`, `{{trees}}`, `{{overlay}}`, `{{contract}}`, `{{commit_help}}`, `{{ticket_example}}`, `{{default_base}}`, `{{test_commands}}`, `{{roles_list}}`, `{{kinds_list}}`, `{{tester_globs}}`.
An unknown placeholder is an error of `effort gen` and of `effortkit check`.

## Example answers

```json
{
  "name": "shop",
  "description": "The web shop: a Django back end and a React front end.",
  "repo": {"url": "git@gitlab.example.com:team/shop.git"},
  "ticket": {"regex": "^SHOP-\\d+$", "example": "SHOP-120"},
  "commit": {"subject_regex": "^(?:SHOP-\\d+: |\\[nojira\\] )\\S", "subject_help": "SHOP-NNN: <subject>"},
  "tests": {
    "commands": ["python3 -m pytest <path>", "npm test -- <path>"],
    "patterns": ["python3 -m pytest(?: \\S+)*", "npm test(?: -- \\S+)?"]
  },
  "forbidden_commands": [
    {"pattern": "^(?:make|npm run) deploy\\b", "reason": "deploy publishes to production.", "fix": "The owner deploys."}
  ],
  "tree_setup": ["npm ci --prefix frontend"],
  "mcp": {"researcher": ["@mcp-web-search"]},
  "improve": {"trigger": "on-close", "threshold": 3}
}
```
