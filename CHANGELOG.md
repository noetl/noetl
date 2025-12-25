# Changelog

All notable changes to this project will be documented in this file.

## [2.3.0](https://github.com/noetl/noetl/compare/v2.2.1...v2.3.0) (2025-12-25)

### Features

* add support for custom PostgreSQL connections ([2317f11](https://github.com/noetl/noetl/commit/2317f11578de9ab4c2b6fd15048b8b9777933778))

## [2.2.1](https://github.com/noetl/noetl/compare/v2.2.0...v2.2.1) (2025-12-24)

### Bug Fixes

* remove .gitmodules file and associated submodule configurations ([538b49a](https://github.com/noetl/noetl/commit/538b49a8d3f05130fa97d6dca44fbc0d86c90305))

## [2.2.0](https://github.com/noetl/noetl/compare/v2.1.4...v2.2.0) (2025-12-24)

### Features

* add Auth0 authentication and session management playbooks ([08f9ffd](https://github.com/noetl/noetl/commit/08f9ffdba893ec9eb218294cd03cf3ce35ebff6a))

### Bug Fixes

* remove .gitmodules file and associated submodule configurations ([4fa2af7](https://github.com/noetl/noetl/commit/4fa2af7a8c155d295a4db105cfca83150d03f85d))

## [2.1.4](https://github.com/noetl/noetl/compare/v2.1.3...v2.1.4) (2025-12-24)

### Bug Fixes

* Enhance logging in NATS command subscriber and worker for better error handling ([f8423eb](https://github.com/noetl/noetl/commit/f8423eb26bf0fce4246bca1d82af27ff84bb5403))

## [2.1.3](https://github.com/noetl/noetl/compare/v2.1.2...v2.1.3) (2025-12-24)

### Bug Fixes

* Replace all print statements with logger ([0eb560e](https://github.com/noetl/noetl/commit/0eb560edc7a500564f255fac939b735ffe2f8b2b))

## [2.1.2](https://github.com/noetl/noetl/compare/v2.1.1...v2.1.2) (2025-12-23)

### Bug Fixes

* update environment variable for server URL to NOETL_SERVER_URL ([ef58d04](https://github.com/noetl/noetl/commit/ef58d04fbeed52a860119bbed3732f5546e90e17))

## [2.1.1](https://github.com/noetl/noetl/compare/v2.1.0...v2.1.1) (2025-12-23)

### Bug Fixes

* enhance logging in V2Worker with context management and improved JSON formatting ([4337fd9](https://github.com/noetl/noetl/commit/4337fd9f0586ae20c62b1d7fbb480ba52a246c41))

## [2.1.0](https://github.com/noetl/noetl/compare/v2.0.3...v2.1.0) (2025-12-23)

### Features

* apply latest keychain and playbook updates ([af77430](https://github.com/noetl/noetl/commit/af77430427ee67ad613dd2666fd54ef63026f4ce))

### Bug Fixes

* Trigger release ([b1230c3](https://github.com/noetl/noetl/commit/b1230c3944d3f27b7f5cb944ddf7655e000f96eb))
* update .gitignore to include all environment files while excluding .env.docker ([dc3567f](https://github.com/noetl/noetl/commit/dc3567f70cdccb6802093d4a122bc0a90f349247))
* update image source in README to use raw GitHub URL ([ba2e3ae](https://github.com/noetl/noetl/commit/ba2e3ae07eb1b294984e2c2f47f2442e9f3450c9))

## [2.0.3](https://github.com/noetl/noetl/compare/v2.0.2...v2.0.3) (2025-12-22)

### Bug Fixes

* enable verbose logging during npm install in Dockerfile ([a91469a](https://github.com/noetl/noetl/commit/a91469ab7c411e6c08301726492b22e8d15d2a95))

## [2.0.2](https://github.com/noetl/noetl/compare/v2.0.1...v2.0.2) (2025-12-21)

### Bug Fixes

* update GitHub metrics extraction to use direct data references for improved accuracy ([f2cfe85](https://github.com/noetl/noetl/commit/f2cfe858de26a461e8e4fa45bc90a51721431598))
* update HTTP iterator playbook to use correct response status code and improve validation logic ([9bd6c56](https://github.com/noetl/noetl/commit/9bd6c56e5cf1403ca04bf13f28b559d791fcafc0))

## [2.0.1](https://github.com/noetl/noetl/compare/v2.0.0...v2.0.1) (2025-12-20)

### Bug Fixes

* enable UI in configmap for improved user interaction ([e0db518](https://github.com/noetl/noetl/commit/e0db5184ca3118cf1f20a88c5feb8178b3328696))

## [2.0.0](https://github.com/noetl/noetl/compare/v1.8.0...v2.0.0) (2025-12-19)

### ⚠ BREAKING CHANGES

* introduce NoETL DSL v2 with event-driven execution model

### Features

* add `schema` column to keychain and credential tables ([53f5cc6](https://github.com/noetl/noetl/commit/53f5cc6c9a930f113e91a15bfb5aa43552da1dde))
* add comprehensive automated tests for playbooks ([0c13024](https://github.com/noetl/noetl/commit/0c13024f08a731bc59eda86ed63dd26dcf193f38))
* add comprehensive test cases and update worker implementation ([46978a6](https://github.com/noetl/noetl/commit/46978a6484bbcd8a1da184dd673c6d638a3e31a3))
* add container and script tool kinds to V2 worker ([50d3569](https://github.com/noetl/noetl/commit/50d35694ee55da57bc00567084c17badaac0153e))
* add detailed event payload models and improve lifecycle event handling ([5e99c56](https://github.com/noetl/noetl/commit/5e99c56963ca87f655e033c2d2155706206b376c))
* add external script loading and inline test playbook ([e24cfc1](https://github.com/noetl/noetl/commit/e24cfc187a8912373f6b4ee03fc31da6ad685955))
* add schema validation support for keychain and credential entries ([7148d25](https://github.com/noetl/noetl/commit/7148d25c134a14da2b62cdfd06b69d3ab6e7ffc9))
* add V2 DuckDB test playbook and implement DuckDB execution in worker ([f2b59ef](https://github.com/noetl/noetl/commit/f2b59ef58874351baffba50db1b949abc08ab79e))
* add workflow completion detection and enhance event tracing ([9df736f](https://github.com/noetl/noetl/commit/9df736ff2978d65ef0f7e098049f08eec56d57da))
* enable navigation to execution page post playbook execution ([a3f945a](https://github.com/noetl/noetl/commit/a3f945a19934a3b2c23ffd57136e2cee06cd4d35))
* enhance function argument handling in V2 worker ([28c180d](https://github.com/noetl/noetl/commit/28c180daa5b71db61606729108d8d7be00535973))
* enhance Postgres execution and credential handling ([54ab5a1](https://github.com/noetl/noetl/commit/54ab5a1e3211c959b2e49276a0ac48149afaf099))
* enhance V2 HTTP test playbook and add debug logging to worker ([e312bf4](https://github.com/noetl/noetl/commit/e312bf4be346800a939cc412b2c572fb4e46776c))
* **events:** add traceability metadata with root_event_id and execution links ([bb48133](https://github.com/noetl/noetl/commit/bb48133b5d7292c3c656fcb3a79f434c662aeb67))
* implement collect+retry pagination support in V2 DSL ([cf98dae](https://github.com/noetl/noetl/commit/cf98dae2dce0fdaaea264d1489a96f78294260f6))
* implement sub-playbook polling and execution state reconstruction ([871c123](https://github.com/noetl/noetl/commit/871c123e3980cbbbca676f6350b23d89facca9b0))
* implement universal end convergence and fix event ordering ([c294deb](https://github.com/noetl/noetl/commit/c294deb5ff45499bbc92fd8fe78e073edcb6e5f2))
* implement vars block feature for v2 DSL ([07ce12a](https://github.com/noetl/noetl/commit/07ce12a599ef1c69e1d019215cc1d86c8f5061a5))
* improve case evaluation and loop handling in V2 engine ([557becd](https://github.com/noetl/noetl/commit/557becda66ba58109e0ac7ae5dea544b977e5c4f))
* improve event metadata handling and retry logic ([47891b1](https://github.com/noetl/noetl/commit/47891b1448fe0e9e5b08e3c97c791d1e76d747c2))
* improve sub-playbook support and duration handling in V2 workflows ([7645eea](https://github.com/noetl/noetl/commit/7645eeaa139ce36bda7cfb9363aa74d76db8b006))
* include node_name in queue persistence for V2 compatibility ([2835c21](https://github.com/noetl/noetl/commit/2835c21d8c6634b8ec288bfd0e4c20bd383094f1))
* integrate keychain resolution for context population and template rendering ([725a212](https://github.com/noetl/noetl/commit/725a212b24aa46e8ea0a8bc758329929c8cfd341))
* introduce architecture design reference for NoETL DSL v2 ([67171bf](https://github.com/noetl/noetl/commit/67171bf13a90671404d4c70942b4f677e3370bb2))
* introduce NoETL DSL v2 with event-driven execution model ([f93ce9b](https://github.com/noetl/noetl/commit/f93ce9befbc1eff52c571a970c5aaf1b25767953))
* **logging:** add VictoriaLogsHandler for streaming logs and custom log formatting ([d52aa5c](https://github.com/noetl/noetl/commit/d52aa5c1e5212f8911a307429d89673526ae5126))
* merge tool_config.args with top-level args in V2 worker ([0f5a8d3](https://github.com/noetl/noetl/commit/0f5a8d326e62aed526ffb6e5a9b3839e2d33d3e8))
* **retry:** implement unified retry logic for error recovery and success-driven tasks ([e424ff8](https://github.com/noetl/noetl/commit/e424ff87d4a3f4f1a47da8190f06a6abac3a53bc))
* **retry:** introduce unified retry logic and event analysis tools ([6806656](https://github.com/noetl/noetl/commit/6806656d13a674fd18628bee2dcc355f1e5d457b))
* update REST API paths and improve payload structure ([2db5e29](https://github.com/noetl/noetl/commit/2db5e29b4f323d76c26f51d65415d368d176421a))

### Bug Fixes

* add render context to enable Jinja2 template rendering in postgres SQL ([1a91946](https://github.com/noetl/noetl/commit/1a91946f5de6e9cb8904153902cdd84035ffb130))
* call async tool executors directly in workbook ([da9cc8e](https://github.com/noetl/noetl/commit/da9cc8e5310cf4f5bb7ae59ccba419e516291bc9))
* check loop completion on step.exit regardless of case commands ([d625491](https://github.com/noetl/noetl/commit/d62549147fd31e887401e8a75aea94fb8b000056))
* correct direction of NOETL_COMMANDS stream in system diagram ([65fd0f8](https://github.com/noetl/noetl/commit/65fd0f83479b643d93d838b04b4415823c062b0c))
* correct sink specification in iterator_save_test ([8e1a3a5](https://github.com/noetl/noetl/commit/8e1a3a57507977ee0613af39dc4d0dfb1d2fb2a0))
* emit loop.done event and add recursive rendering for sink ([59ac3fc](https://github.com/noetl/noetl/commit/59ac3fcf4bd5757991c3ca2713eb9b28170186c9))
* enforce architectural separation for auth_cache management via service layer ([1453d37](https://github.com/noetl/noetl/commit/1453d37bf84d26f888d93a3ea99faa8b1426617d))
* **engine:** allow completion events (workflow_failed, playbook_failed) to be emitted before stopping execution ([27c3533](https://github.com/noetl/noetl/commit/27c3533c23d387dd97f8bf13217fb6be04912dff))
* **engine:** skip structural next transitions when step fails ([c47d6c2](https://github.com/noetl/noetl/commit/c47d6c2487127fed9c53f4ec0835f32df38621c7))
* **engine:** stop execution when step fails (FAILED status or command.failed event) ([2b39a16](https://github.com/noetl/noetl/commit/2b39a16de88ca49cc936f9892fc1ecf75671530a))
* **error-handling:** properly detect and fail on tool errors ([f0a18c6](https://github.com/noetl/noetl/commit/f0a18c68f13c44cfc786486fda4117e95dc4adf9))
* **events:** use consistent dot notation for lifecycle event types ([fcb80bf](https://github.com/noetl/noetl/commit/fcb80bf53bbff28681b5cd5a21bfdf8a0b92a81c))
* explicitly check and mark loop completion on step.exit ([82f272b](https://github.com/noetl/noetl/commit/82f272bfdd965de7a3b7b86358cc8586960790ab))
* improve error logging in V2 worker and add Google OAuth credentials fixture ([0c0db74](https://github.com/noetl/noetl/commit/0c0db745197f262cd7b1f1422506cec17aad622a))
* integrate keychain resolution for context population and template rendering ([61a55c8](https://github.com/noetl/noetl/commit/61a55c898e32ee5f7b73858f23275c8d804845fd))
* integrate NATS JetStream for event-driven command execution ([8cdb790](https://github.com/noetl/noetl/commit/8cdb7904a59a1aeef076baa5b9e6c3c49fb083a0))
* **keychain:** fix credential API endpoint and support authorized_user credentials ([dd7533a](https://github.com/noetl/noetl/commit/dd7533aa4d9aaf66c8992320bb44792d165170b4))
* **keychain:** remove duplicate keychain processing in V2 API ([6b9959d](https://github.com/noetl/noetl/commit/6b9959d99eb39f58ec1f8a73e578d5d80e83c3bb))
* **keychain:** remove try-catch blocks, allow failures to crash ([4446e27](https://github.com/noetl/noetl/commit/4446e2742d54d48110f96c48d50b2440e0560e2f))
* **keychain:** use correct API port 8082 for keychain resolution ([7193a43](https://github.com/noetl/noetl/commit/7193a4351b1c61f965d8836f476c0c25a6ed646c))
* move loop to step level in playbook_composition ([794a8f8](https://github.com/noetl/noetl/commit/794a8f8b6852d27226ba23e90e4ed4d3234f3e7b))
* **nats:** acknowledge messages immediately to prevent redelivery ([ce62d6b](https://github.com/noetl/noetl/commit/ce62d6b612b9af69fd0c2779223994e84a64ddd9))
* **nats:** ensure exactly-once message delivery ([c4be42c](https://github.com/noetl/noetl/commit/c4be42c5b129fe2499679ebac76433cf9d1ce219))
* persist loop_state in state data (though currently unused due to event sourcing) ([bf0a558](https://github.com/noetl/noetl/commit/bf0a558e32b065f6dd49fb2e3c1773dc5dbf001e))
* remove escaped quotes in YAML Python code blocks ([d590ee5](https://github.com/noetl/noetl/commit/d590ee552bc1413cc754f3bc30e6d3617b2b5f3e))
* reorganize packages and rename transient storage ([e00564d](https://github.com/noetl/noetl/commit/e00564d24cc15b6a40beab5a55a39921675e8de4))
* replace `events_v2` with `v2` API and simplify control flow engine ([1ab2f61](https://github.com/noetl/noetl/commit/1ab2f61dfc7f8c9b3188c8b3c09f99c1829e7005))
* **server:** fix execution_id context protection and remove from playbook workload ([8817dfb](https://github.com/noetl/noetl/commit/8817dfb81b508b4a957c6026744a3b6f0bf04884))
* **server:** protect execution_id from workload override ([88f0057](https://github.com/noetl/noetl/commit/88f005778f1b92d3fc6eef04ecf99dd3ba9bae16))
* **status:** use uppercase FAILED status in worker events ([21d1bfe](https://github.com/noetl/noetl/commit/21d1bfe2fa04ed5febb9bd4769516d727de566dd))
* **status:** use uppercase PENDING for command.issued events ([5f56dc6](https://github.com/noetl/noetl/commit/5f56dc65b8a8cbd26183757d339b1a02ddf1af13))
* use 'auth' instead of 'connection' in sink spec ([059da45](https://github.com/noetl/noetl/commit/059da45bf962c77ca1bba041991edaa067a84c86))
* use 'tool' instead of 'backend' in sink command config ([53a0d44](https://github.com/noetl/noetl/commit/53a0d4493acb31b49d338f1b6d0a9cdb51b6f257))
* **v2:** add keychain processing to V2 API start_execution ([2169b02](https://github.com/noetl/noetl/commit/2169b0233eeb5c0dcb79aaa439d625edc11217cb))
* wire snowflake transfer and serialize snowflake results ([5dcb11c](https://github.com/noetl/noetl/commit/5dcb11cef0e8fd220e01df4d9d7a24a6cef63c0e))

## [1.8.0](https://github.com/noetl/noetl/compare/v1.7.1...v1.8.0) (2025-12-09)

### Features

* implement Amadeus AI chat interface with GraphQL integration and CORS support ([aa6cde2](https://github.com/noetl/noetl/commit/aa6cde227ef3da7620536d1731903a939b59446f))
* **orchestration:** enhance loop execution logic and unify event handling ([c5e32bd](https://github.com/noetl/noetl/commit/c5e32bd65762209413260b1e14309855b48a2a59))
* **orchestration:** implement dynamic template rendering for collections ([d074dca](https://github.com/noetl/noetl/commit/d074dca699363c09f9786e7c59aeff8f1dfed8b1))
* **retry:** enhance retry configuration and testing with detailed conditions ([c20a20d](https://github.com/noetl/noetl/commit/c20a20d7cb2a8cfadc184649bd008383a2d7e0d2))

### Bug Fixes

* add critical analysis and fix proposal for loop completion bug ([e535186](https://github.com/noetl/noetl/commit/e535186ee2bb4741dbed287202c26e46b4a2fa6c))
* enhance sink restoration, workload handling, and template rendering ([e6331ce](https://github.com/noetl/noetl/commit/e6331cedb482982609dcf709f93aee424b090038))
* handle None error messages in job execution metadata ([4253e0a](https://github.com/noetl/noetl/commit/4253e0a815f2041ead63fee85ecb70c86f3d34d7))
* Increase HTTP client timeout to 120s to support complex template rendering ([8845358](https://github.com/noetl/noetl/commit/8845358372b5ae9808135fac2d9f5808a9b00fac))
* streamline content, focus on key workflows and usage scenarios with semantic-release. ([389d64d](https://github.com/noetl/noetl/commit/389d64d26062665c7140b84564ee54787d194c70))
* Test Semantic Release with branch protection rule ([48317d4](https://github.com/noetl/noetl/commit/48317d433c0b2a9c2dc20af49073150c0b7feb5a))
* **tests:** update `regression_dashboard.ipynb` to convert RecordBatchReader to Table before writing parquet file ([79f5ea4](https://github.com/noetl/noetl/commit/79f5ea4509531f884a93019218decbd8b28344fc))
* update application configuration in env.example for router port and base URL ([aaa1fb9](https://github.com/noetl/noetl/commit/aaa1fb95a55dccfbda1ffe4079797c0b2bc1318d))
* update title and header to reflect Cybx AI branding ([3611bb6](https://github.com/noetl/noetl/commit/3611bb6f0248197aad8164667812c2bd43af3deb))

## [1.7.1](https://github.com/noetl/noetl/compare/v1.7.0...v1.7.1) (2025-12-05)

### Bug Fixes

* Tshoot tags ([e054773](https://github.com/noetl/noetl/commit/e0547739f3c1388ceff2cfd60890a0a3f93cf18e))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-12-05)

### Features

* Add credential management UI with Snowflake RSA key-pair support ([9f9ab63](https://github.com/noetl/noetl/commit/9f9ab637e2e13153be361b5455274565a57afa70))
* add Credentials component with API integration for credential management ([79c7329](https://github.com/noetl/noetl/commit/79c73299d36eb63152641fbc47cecb22a78099e2))
* add credentials management tab with catalog-like design ([267f673](https://github.com/noetl/noetl/commit/267f673149f1da8da17d9a6418d4550f6657805f))
* add playbook creation functionality with modal and API integration ([cc6deeb](https://github.com/noetl/noetl/commit/cc6deeb2c53fc1597ece728a10923ea70f4f6e58))
* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))
* enhance execute_playbook documentation and add execution status details ([740f522](https://github.com/noetl/noetl/commit/740f5220b7c01cdc1232c0107dfe39cd0ffd6256))
* enhance GoogleTokenProvider for effective audience resolution and lazy imports for container execution ([ff8819c](https://github.com/noetl/noetl/commit/ff8819c87b2d5b78b11d5eaf92b5f9a50b25f1c6))
* refactor gateway structure and update dependencies ([ac3d5e5](https://github.com/noetl/noetl/commit/ac3d5e5f7723101378f4086c78f79028b1e73168))

### Bug Fixes

* add ui-src and documentation node_modules to ignore list ([b99aae1](https://github.com/noetl/noetl/commit/b99aae10adbf8e4ca19a7cdd641ef02f4309cff0))
* Fix Release workflow ([8209c11](https://github.com/noetl/noetl/commit/8209c11ef9ec71e9b471dce250e3dd6bbc79bb24))
* reduce padding in catalog loading, error, and main content sections ([6580922](https://github.com/noetl/noetl/commit/65809221d31e309798a94e19f3cee3b62a7ed6f3))
* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))
* Tshoot tags ([90253b0](https://github.com/noetl/noetl/commit/90253b0baf9d0e5a7983db18f581f7eaaf442fae))
* Update Build GitHub workflow ([ab66c0d](https://github.com/noetl/noetl/commit/ab66c0d085cfeaa20e8a538349fbb7d0d611bb83))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-12-05)

### Features

* Add credential management UI with Snowflake RSA key-pair support ([9f9ab63](https://github.com/noetl/noetl/commit/9f9ab637e2e13153be361b5455274565a57afa70))
* add Credentials component with API integration for credential management ([79c7329](https://github.com/noetl/noetl/commit/79c73299d36eb63152641fbc47cecb22a78099e2))
* add credentials management tab with catalog-like design ([267f673](https://github.com/noetl/noetl/commit/267f673149f1da8da17d9a6418d4550f6657805f))
* add playbook creation functionality with modal and API integration ([cc6deeb](https://github.com/noetl/noetl/commit/cc6deeb2c53fc1597ece728a10923ea70f4f6e58))
* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))
* enhance execute_playbook documentation and add execution status details ([740f522](https://github.com/noetl/noetl/commit/740f5220b7c01cdc1232c0107dfe39cd0ffd6256))
* enhance GoogleTokenProvider for effective audience resolution and lazy imports for container execution ([ff8819c](https://github.com/noetl/noetl/commit/ff8819c87b2d5b78b11d5eaf92b5f9a50b25f1c6))
* refactor gateway structure and update dependencies ([ac3d5e5](https://github.com/noetl/noetl/commit/ac3d5e5f7723101378f4086c78f79028b1e73168))

### Bug Fixes

* add ui-src and documentation node_modules to ignore list ([b99aae1](https://github.com/noetl/noetl/commit/b99aae10adbf8e4ca19a7cdd641ef02f4309cff0))
* Fix Release workflow ([8209c11](https://github.com/noetl/noetl/commit/8209c11ef9ec71e9b471dce250e3dd6bbc79bb24))
* reduce padding in catalog loading, error, and main content sections ([6580922](https://github.com/noetl/noetl/commit/65809221d31e309798a94e19f3cee3b62a7ed6f3))
* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))
* Update Build GitHub workflow ([ab66c0d](https://github.com/noetl/noetl/commit/ab66c0d085cfeaa20e8a538349fbb7d0d611bb83))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-12-05)

### Features

* Add credential management UI with Snowflake RSA key-pair support ([9f9ab63](https://github.com/noetl/noetl/commit/9f9ab637e2e13153be361b5455274565a57afa70))
* add Credentials component with API integration for credential management ([79c7329](https://github.com/noetl/noetl/commit/79c73299d36eb63152641fbc47cecb22a78099e2))
* add credentials management tab with catalog-like design ([267f673](https://github.com/noetl/noetl/commit/267f673149f1da8da17d9a6418d4550f6657805f))
* add playbook creation functionality with modal and API integration ([cc6deeb](https://github.com/noetl/noetl/commit/cc6deeb2c53fc1597ece728a10923ea70f4f6e58))
* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))
* enhance execute_playbook documentation and add execution status details ([740f522](https://github.com/noetl/noetl/commit/740f5220b7c01cdc1232c0107dfe39cd0ffd6256))
* enhance GoogleTokenProvider for effective audience resolution and lazy imports for container execution ([ff8819c](https://github.com/noetl/noetl/commit/ff8819c87b2d5b78b11d5eaf92b5f9a50b25f1c6))
* refactor gateway structure and update dependencies ([ac3d5e5](https://github.com/noetl/noetl/commit/ac3d5e5f7723101378f4086c78f79028b1e73168))

### Bug Fixes

* add ui-src and documentation node_modules to ignore list ([b99aae1](https://github.com/noetl/noetl/commit/b99aae10adbf8e4ca19a7cdd641ef02f4309cff0))
* reduce padding in catalog loading, error, and main content sections ([6580922](https://github.com/noetl/noetl/commit/65809221d31e309798a94e19f3cee3b62a7ed6f3))
* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-12-04)

### Features

* Add credential management UI with Snowflake RSA key-pair support ([9f9ab63](https://github.com/noetl/noetl/commit/9f9ab637e2e13153be361b5455274565a57afa70))
* add Credentials component with API integration for credential management ([79c7329](https://github.com/noetl/noetl/commit/79c73299d36eb63152641fbc47cecb22a78099e2))
* add credentials management tab with catalog-like design ([267f673](https://github.com/noetl/noetl/commit/267f673149f1da8da17d9a6418d4550f6657805f))
* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))
* enhance GoogleTokenProvider for effective audience resolution and lazy imports for container execution ([ff8819c](https://github.com/noetl/noetl/commit/ff8819c87b2d5b78b11d5eaf92b5f9a50b25f1c6))
* refactor gateway structure and update dependencies ([ac3d5e5](https://github.com/noetl/noetl/commit/ac3d5e5f7723101378f4086c78f79028b1e73168))

### Bug Fixes

* add ui-src and documentation node_modules to ignore list ([b99aae1](https://github.com/noetl/noetl/commit/b99aae10adbf8e4ca19a7cdd641ef02f4309cff0))
* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-12-04)

### Features

* Add credential management UI with Snowflake RSA key-pair support ([9f9ab63](https://github.com/noetl/noetl/commit/9f9ab637e2e13153be361b5455274565a57afa70))
* add Credentials component with API integration for credential management ([79c7329](https://github.com/noetl/noetl/commit/79c73299d36eb63152641fbc47cecb22a78099e2))
* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))
* enhance GoogleTokenProvider for effective audience resolution and lazy imports for container execution ([ff8819c](https://github.com/noetl/noetl/commit/ff8819c87b2d5b78b11d5eaf92b5f9a50b25f1c6))

### Bug Fixes

* add ui-src and documentation node_modules to ignore list ([b99aae1](https://github.com/noetl/noetl/commit/b99aae10adbf8e4ca19a7cdd641ef02f4309cff0))
* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-12-03)

### Features

* Add credential management UI with Snowflake RSA key-pair support ([9f9ab63](https://github.com/noetl/noetl/commit/9f9ab637e2e13153be361b5455274565a57afa70))
* add Credentials component with API integration for credential management ([79c7329](https://github.com/noetl/noetl/commit/79c73299d36eb63152641fbc47cecb22a78099e2))
* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))
* enhance GoogleTokenProvider for effective audience resolution and lazy imports for container execution ([ff8819c](https://github.com/noetl/noetl/commit/ff8819c87b2d5b78b11d5eaf92b5f9a50b25f1c6))

### Bug Fixes

* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-12-03)

### Features

* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))
* enhance GoogleTokenProvider for effective audience resolution and lazy imports for container execution ([ff8819c](https://github.com/noetl/noetl/commit/ff8819c87b2d5b78b11d5eaf92b5f9a50b25f1c6))

### Bug Fixes

* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-11-28)

### Features

* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))

### Bug Fixes

* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-11-28)

### Features

* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))

### Bug Fixes

* support effective audience resolution in token provider ([5034593](https://github.com/noetl/noetl/commit/503459359e5d26592a844ce2f1409ced19cf5779))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-11-28)

### Features

* container secrets ([f6a1391](https://github.com/noetl/noetl/commit/f6a1391f3bb2437add043b48610dddd5625287ff))
* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-11-28)

### Features

* **container:** add container tool with authenticated remote file downloads ([fa8c1db](https://github.com/noetl/noetl/commit/fa8c1db48b21db7ff87c1126e99cc8ba36d67449))

## [1.4.0](https://github.com/noetl/noetl/compare/v1.3.0...v1.4.0) (2025-11-28)

### Features

* **container:** enhance job creation with remote file downloads and optional ConfigMap ([4104fbb](https://github.com/noetl/noetl/commit/4104fbb7e42445f5916f1043232f171b96d1c155))

## [1.3.0](https://github.com/noetl/noetl/compare/v1.2.5...v1.3.0) (2025-11-27)

### Features

* **container:** add container tool executor ([2a0010e](https://github.com/noetl/noetl/commit/2a0010ef2ed134216c7de4103976c102164af5a8))

## [1.2.5](https://github.com/noetl/noetl/compare/v1.2.4...v1.2.5) (2025-11-26)

### Bug Fixes

* Preserve loop variables from server-side rendering ([d7c5b41](https://github.com/noetl/noetl/commit/d7c5b41bdc6ecdde5e39a4d05f9da21f389763af))
* version loop ([0b8c664](https://github.com/noetl/noetl/commit/0b8c664a984df7a5a1e50980b2e8416cee0f363a))

## [1.2.4](https://github.com/noetl/noetl/compare/v1.2.3...v1.2.4) (2025-11-25)

### Bug Fixes

* Fix Release label ([5abe9b8](https://github.com/noetl/noetl/commit/5abe9b87e0c71c97406c4b9162d16a20dc0cf584))

## [1.2.3](https://github.com/noetl/noetl/compare/v1.2.2...v1.2.3) (2025-11-25)

### Bug Fixes

* CI/CD test build ([0f994c3](https://github.com/noetl/noetl/commit/0f994c3fd0dae8eb9a43ae7449e29d2d9fabec84))
* Update Release GitHub workflow ([68b34f2](https://github.com/noetl/noetl/commit/68b34f2e4e234f122c80261b3c55e79fd23dfa11))

# Changelog

## [Unreleased] - Unified Kubernetes Deployment

### Fixed
- **UI Execute Endpoint (Issue #97)**: Fixed 405 Method Not Allowed error when executing playbooks with payload from UI
  - Updated UI to call existing `/api/run/playbook` endpoint instead of non-existent `/execute` endpoint
  - Added backward compatibility for `input_payload` field name (normalizes to `args`)
  - Schema now accepts `args`, `parameters`, or `input_payload` for execution parameters
  - Legacy `sync_to_postgres` field is now removed during validation
  - Files modified: `ui-src/src/services/api.ts`, `noetl/server/api/run/schema.py`

### Security

#### JavaScript Dependencies
- **[HIGH]** Updated `axios` from 1.6.0 to 1.12.0 to fix DoS vulnerability (GHSA-4hjh-wcwx-xvwj, CVE-2024-XXXXX, CWE-770: Allocation of Resources Without Limits)
  - Axios was vulnerable to Denial of Service attacks through lack of data size validation
  - Fixed in axios@1.12.0+
- **[MODERATE]** Updated `vite` from 7.0.3 to 7.0.8 to fix multiple path traversal vulnerabilities:
  - GHSA-93m4-6634-74q7: `server.fs.deny` bypass via backslash on Windows (CWE-22)
  - GHSA-g4jq-h2w9-997c: Middleware may serve files with same name prefix as public directory (CWE-22, CWE-200, CWE-284)
  - GHSA-jqfw-vq24-v9c3: `server.fs` settings not applied to HTML files (CWE-23, CWE-200, CWE-284)
  - Fixed in vite@7.0.8+

#### Python Dependencies
- **[HIGH]** Updated `authlib` from 1.6.4 to 1.6.5 to fix multiple DoS vulnerabilities:
  - GHSA-pq5p-34cr-23v9: JWS/JWT token DoS via unbounded segment processing (CVSS 7.5, CWE-770)
  - GHSA-g7f3-828f-7h7m: JWE DEFLATE decompression bomb vulnerability (CVSS 6.5, CWE-409)
  - Fixed in authlib@1.6.5+
- **[HIGH]** Updated `starlette` from 0.48.0 to 0.49.3 to fix Range header DoS vulnerability (GHSA-7f5h-v6xp-fcq8, CVSS 7.5, CWE-400)
  - Starlette was vulnerable to quadratic-time complexity attacks via malicious Range headers
  - Fixed in starlette@0.49.1+ (upgraded to 0.49.3 via fastapi dependency)
- **[MODERATE]** Updated `deepdiff` from 8.5.0 to 8.6.1 to fix vulnerability (GHSA-mw26-5g2v-hqw3)
  - Fixed in deepdiff@8.6.1+
- **[MODERATE]** Updated `fastapi` from 0.116.1 to 0.120.4 to ensure starlette security fixes
  - Upgraded to pull in patched starlette version

#### System-Level
- **[MODERATE]** Updated `pip` from 24.3.1 to 25.3 to fix tarfile path traversal vulnerability (GHSA-4xh5-x5gv-qwph)
  - Pip was vulnerable to symlink-based path traversal during package installation
  - Fixed in pip@25.3+ (system-level upgrade)

**Security Status**: ✅ All 8 vulnerabilities resolved - 0 remaining vulnerabilities

### Added
- **Unified Kubernetes Deployment**: New deployment architecture that consolidates all NoETL components (server, workers, observability) into a single namespace
- **Integrated Observability**: Built-in Grafana, VictoriaMetrics, VictoriaLogs, and Vector monitoring stack
- **Simplified Management**: All components deployed and managed together
- **Build and Load Scripts**: Automated Docker image building and loading for Kind clusters
- **Port-Forward Management**: Automated port-forwarding setup for observability UIs

### Scripts Added
- `k8s/deploy-unified-platform.sh` - Main unified deployment script
- `k8s/generate-unified-noetl-deployment.sh` - Generates unified Kubernetes manifests
- `k8s/deploy-unified-observability.sh` - Deploys observability stack to unified namespace
- `k8s/build-and-load-images.sh` - Builds and loads Docker images into Kind cluster
- `k8s/cleanup-old-deployments.sh` - Cleans up legacy separate deployments

### Documentation Added
- `docs/unified_deployment.md` - Comprehensive unified deployment guide
- `k8s/UNIFIED_DEPLOYMENT.md` - Quick reference for unified deployment
- Updated `docs/installation.md` with Kubernetes installation option
- Updated `docs/kind_kubernetes.md` with unified deployment examples
- Updated `k8s/README.md` with unified vs legacy deployment comparison

### Benefits
- **Simplified Architecture**: Single namespace (`noetl-platform`) instead of 5 separate namespaces
- **Better Performance**: Direct service-to-service communication without cross-namespace networking
- **Unified Monitoring**: All components automatically monitored in one dashboard
- **Easier Troubleshooting**: Everything in one location
- **Resource Efficiency**: Reduced Kubernetes overhead

### Migration
- Use `./k8s/cleanup-old-deployments.sh` to migrate from legacy separate namespace deployment
- Maintains API compatibility with existing clients
- PostgreSQL remains in separate `postgres` namespace for data persistence

## [0.1.26] (2025-07-17)

Changes Made:
1. Updated noetl/main.py
Added a --no-ui flag to the server command
Modified the create_app() function to support UI enable/disable through a global variable
Added support for the NOETL_ENABLE_UI environment variable (defaults to "true")
The server now logs whether UI is enabled or disabled on startup
2. Updated Docker Configuration
Modified docker/noetl/development/Dockerfile to use the new CLI structure
Added NOETL_ENABLE_UI=true environment variable
Updated the CMD to use the new server command format
3. Enhanced scripts/build_ui.sh
Added --with-server option to start both UI and NoETL server together
Added new dev-with-server mode
Updated usage documentation to include the new options
How to Use:
Running the Server:
With UI (default):
python -m noetl.main server --host 0.0.0.0 --port 8080
Without UI:
python -m noetl.main server --host 0.0.0.0 --port 8080 --no-ui
Using environment variable:
NOETL_ENABLE_UI=false python -m noetl.main server --host 0.0.0.0 --port 8080
Building and Running UI:
Build UI for production:
./scripts/build_ui.sh -p 8080
Start UI development server with NoETL server:
./scripts/build_ui.sh --with-server -p 8080
Start UI development server (expects external NoETL server):
./scripts/build_ui.sh -m dev -p 8080
Docker Usage:
With UI (default):
docker run -p 8080:8080 noetl:latest
Without UI:
docker run -e NOETL_ENABLE_UI=false -p 8080:8080 noetl:latest
Key Features:
Backward Compatibility: Default behavior remains unchanged (UI enabled)
Environment Variable Support: Can be controlled via NOETL_ENABLE_UI
CLI Flag: --no-ui flag for explicit UI disabling
Docker Support: Environment variable works in containerized environments
Development Integration: Build script can start both servers together
Proper Logging: Clear indication of UI status on server startup
The implementation allows for flexible deployment scenarios where you can run the NoETL server as an API-only service or with the full UI depending on your needs.

## [0.1.18] (2025-06-29)

### Features

* **packaging**: Include UI components, static files and templates, in the package distribution
* **packaging**: Add package metadata including classifiers, keywords, and project URLs
* **packaging**: Update pyproject.toml with packaging standards
* **packaging**: Create ui package with __init__.py for UI components inclusion
* **packaging**: Add MANIFEST.in for file inclusion in distribution
* **packaging**: all CSS, JS, and HTML template files are bundled with the package

### Changed

* **version**: Bump version from 0.1.17 to 0.1.18
* **packaging**: Modernize setup.py with metadata and package data configuration
* **structure**: Make ui folder and Python package for distribution

### Removed

* **packaging**: Remove obsolete migration references from package configuration

## [0.1.0](https://github.com/noetl/noetl/compare/v0.0.1...v0.1.0) (2023-12-20)


### Features

* Add Semantic release SWP-98 ([2ac157e](https://github.com/noetl/noetl/commit/2ac157eb76ba43c974c604c235edf3e6caa7f931))
