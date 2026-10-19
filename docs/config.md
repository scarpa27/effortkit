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
| `tests.commands` | `[]` | The test commands, as you run them, for example `mvn -pl <module> -am test`. A `<placeholder>` stands for one word, and more flags (words that start with `-`) may go anywhere. A matching command needs no approval, and the reviewer and the debugger may run it. |
| `tests.patterns` | `[]` | Advanced: full-match regexes over the words of one command, joined by single spaces, for a form that `tests.commands` cannot express. |
| `tester_globs` | common test folders | The files that the tester may change, as globs relative to the tree root. |
| `forbidden_commands` | `[]` | `{"pattern", "reason", "fix"}` entries. The gate refuses a command whose words match `pattern` for every role, also after the approval. |
| `build_dirs` | build output names | Folder names where `rm -r` is allowed. |
| `tree_excludes` | `[]` | Lines for `info/exclude` of the repository, for files that every tree creates. |
| `tree_setup` | `[]` | Shell commands that `effort new` runs in a new tree of the project, for example `npm ci`. The owner wrote them, so no gate judges them. |
| `secrets.files`, `secrets.dirs`, `secrets.names` | `[]` | More credential paths and file names, on top of the built-in list (`~/.ssh`, `~/.git-credentials`, `.env` and others). |
| `max_efforts` | `8` | The limit of open efforts with a tree. |
| `models.default` | `claude-opus-5.5` | The model of every role without its own entry. `effortkit check --validate` checks each model against `kiro-cli chat --list-models`. |
| `models.<role>` | sonnet for tester and reviewer | The model of one role. |
| `mcp.<role>` | `[]` | MCP tools of one role, for example `["@mcp-web-search"]`. A listed role loads `~/.kiro/settings/mcp.json`. |
| `skills.<role>` | `{}` | More skills for one role, by name. A name resolves to `skills/` of the kit or `overlay/skills/` of the instance. A skill of the overlay that some `skills.<role>` names goes only to those roles. |
| `skills_off` | `[]` | Kit skills that no role of this instance loads, for example `lavish` on a machine without Node. |
| `roles.<name>` | the built-in roles | A custom role, or a change to a built-in one: `profile`, `description`, `artifact`, `model`, `web`, `tree_globs`, `resources`, `skills`. A custom role needs its prompt in `overlay/agents/<name>.md`. Its `skills` replace the default `caveman` and `asd-ste100`. `null` switches a built-in role off. |
| `kinds.<name>` | the built-in kinds | A custom kind: `repo` (`product`, `kit`, `instance` or `null`), `lane` (a skill name), `stage`, `about`, `detached`, `base`. |
| `improve.trigger` | `on-close` | `on-close`: `effort close` starts an improvement round when the open reports reach the threshold. `manual`: only `effort improve` starts one. |
| `improve.threshold` | `3` | The number of open reports that starts a round on close. |
| `style.ste100` | `false` | The artifacts follow ASD-STE100, with the `asd-ste100` skill. |
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

## Skills

Every skill that an agent loads ships with the kit or with the overlay.
`effort gen` copies each of them into `<instance>/.kiro/skills/<name>/`, and the agent configs name only those copies.
The sessions run with `KIRO_HOME=<instance>/.kiro-home`, which links only the settings and the MCP servers of the machine.
So no agent loads a skill or a steering file of the machine, and `~/.kiro` can change without effect on an instance.
kiro-cli shows every installed skill to every agent of the instance. The table names the roles that install each skill and name it in their resources.

| Skill | Roles | Source |
|---|---|---|
| `plan-review`, `lane-*` | supervisor | the kit |
| `lavish` | supervisor, installer | lavish-axi v0.1.88, MIT |
| `grill-me`, `grilling` | supervisor, installer | mattpocock/skills, MIT |
| `caveman`, `ultracave`, `megacave` | every role | caveman v4.0.1, Apache-2.0 |
| `asd-ste100` | every role | danyuchn/asd-ste100-skill, MIT |
| `web-search` | researcher, with `mcp.researcher` holding `@mcp-web-search` | the owner's skill |
| `engineering-writeup` | supervisor | the owner's skill, with neutral examples |
| `diagnostic-experiment-matrix` | supervisor, debugger | the owner's skill |

`skills/skills-lock.json` records the source, the version, the licence and the hash of each skill that the kit did not write.
`effortkit skills` lists them, and `effortkit check` reports a copy that differs from its hash.

## Overlay

| Path | Use |
|---|---|
| `overlay/steering/*.md` | Project steering for every role: what the project is, its layout, build, tests, conventions and traps. |
| `overlay/agents/<role>.md` | Project rules for one role. The generator appends the file to the kit prompt of the role. The prompt of a custom role is this file alone. |
| `overlay/skills/<name>/` | Project skills, and the lane skills of custom kinds. Copy a skill from another place into this folder. A skill here replaces the kit skill of the same name. |

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
  "tests": {"commands": ["python3 -m pytest <path>", "npm test -- <path>"]},
  "forbidden_commands": [
    {"pattern": "^(?:make|npm run) deploy\\b", "reason": "deploy publishes to production.", "fix": "The owner deploys."}
  ],
  "tree_setup": ["npm ci --prefix frontend"],
  "mcp": {"researcher": ["@mcp-web-search"]},
  "improve": {"trigger": "on-close", "threshold": 3}
}
```
