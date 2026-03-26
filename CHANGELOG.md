# Changelog

All notable changes to this project will be documented in this file.

## [2.12.4](https://github.com/noetl/noetl/compare/v2.12.3...v2.12.4) (2026-03-26)

### Bug Fixes

* **postgres:** enforce auth contract and pgbouncer routing ([5070b02](https://github.com/noetl/noetl/commit/5070b027ffe6fc856167cf6ad37a8fd95653ac3d))
* **review:** address copilot feedback for postgres auth contract ([9a27889](https://github.com/noetl/noetl/commit/9a27889dbe612cc79e8e76094cc5b876749e3b95))

## [2.12.3](https://github.com/noetl/noetl/compare/v2.12.2...v2.12.3) (2026-03-26)

### Bug Fixes

* **loop:** allow valid 1-item parallel snapshot restore ([ddcd425](https://github.com/noetl/noetl/commit/ddcd425440da4593fda950e52142f413b8442774))
* **loop:** prevent tiny snapshot restore from collapsing parallel loops ([e965283](https://github.com/noetl/noetl/commit/e965283efbb52aae5f2b4ae47efca561f6acbce1))

## [2.12.2](https://github.com/noetl/noetl/compare/v2.12.1...v2.12.2) (2026-03-26)

### Bug Fixes

* **loop:** address review findings for snapshot restore safety ([e0ce2e9](https://github.com/noetl/noetl/commit/e0ce2e94dd4d90c6bff900a3649923f9cb5680fe))
* **loop:** preserve loop collections across stale-cache replay ([ffb069d](https://github.com/noetl/noetl/commit/ffb069d9b46ef8dd3fdffaf8b01767cb8c7ddea6))

## [2.12.1](https://github.com/noetl/noetl/compare/v2.12.0...v2.12.1) (2026-03-26)

### Bug Fixes

* **dsl:** narrow context promotion and wrap proxy getitem dicts ([4f1cfd6](https://github.com/noetl/noetl/commit/4f1cfd6c4f76995f145223ce9fcf485f8b11ddea))
* **dsl:** restore set_ctx compatibility for reference-only context results ([386b3e2](https://github.com/noetl/noetl/commit/386b3e283713072efd744b5e19bb039712d9fce0))

## [2.12.0](https://github.com/noetl/noetl/compare/v2.11.0...v2.12.0) (2026-03-26)

### Features

* **task-sequence:** add previous-jump replay for missing references ([8b380eb](https://github.com/noetl/noetl/commit/8b380eb98a870ad3b31797821574d19fde51a8c7))

### Bug Fixes

* **copilot:** harden context sizing and reference detection ([13fd313](https://github.com/noetl/noetl/commit/13fd3138e5d2616bd1da653b8655aed1dd7f5cb5))
* **server:** bound derived context rows and retain compact routing keys ([87a62d8](https://github.com/noetl/noetl/commit/87a62d8ff07b49717497d8d68463ef104d54cbf1))
* **server:** derive bounded context from response envelope for reference-only events ([659622c](https://github.com/noetl/noetl/commit/659622c83f4c8078fc254a6066b365c352be7767))

## [2.11.0](https://github.com/noetl/noetl/compare/v2.10.42...v2.11.0) (2026-03-26)

### Features

* **runtime:** enforce reference-only event.result contract ([f726aff](https://github.com/noetl/noetl/commit/f726aff6fbea4c73574dec092097d59097456c1f))

### Performance Improvements

* **runtime:** reduce reaper and state-replay DB pressure ([2dc5fe4](https://github.com/noetl/noetl/commit/2dc5fe498a7ebff0c6783fa1309e0f4640c3796b))
* **state:** trim replay scope and reduce stale-cache churn ([399dea7](https://github.com/noetl/noetl/commit/399dea7070c4c3781e4b1ca9be151e107b8ce369))

## [2.10.42](https://github.com/noetl/noetl/compare/v2.10.41...v2.10.42) (2026-03-26)

### Bug Fixes

* **engine:** skip workflow.failed when command.failed arrives with pending recovery ([5a38cae](https://github.com/noetl/noetl/commit/5a38cae1f36a332eb4115999d6e3111bcd119e14))

## [2.10.41](https://github.com/noetl/noetl/compare/v2.10.40...v2.10.41) (2026-03-25)

### Bug Fixes

* **config:** wire NOETL_WORKER_CONCURRENCY_PROBE_INTERVAL into get_worker_settings and validate ([da49706](https://github.com/noetl/noetl/commit/da497068bfbf280d0df5ed0c8ffa2e8148634396)), closes [PR#328](https://github.com/noetl/PR/issues/328)
* **worker:** make concurrency probe interval configurable, default 2s ([8d37f5f](https://github.com/noetl/noetl/commit/8d37f5fdb151f2a475ac6b5aba73846f65d1c31f))

## [2.10.40](https://github.com/noetl/noetl/compare/v2.10.39...v2.10.40) (2026-03-25)

### Bug Fixes

* **engine:** address copilot review comments on PR326 ([a420948](https://github.com/noetl/noetl/commit/a420948c304e06da45aacab7ae09e3f67d9638fc))
* **engine:** return any_matched not any_actionable_issued from next transition eval ([fa7ee2c](https://github.com/noetl/noetl/commit/fa7ee2cdb60a5e6fa260dc2ef2b450f7f214a532))

## [2.10.39](https://github.com/noetl/noetl/compare/v2.10.38...v2.10.39) (2026-03-25)

### Bug Fixes

* **runtime:** stop terminal executions from leaking commands ([e71797a](https://github.com/noetl/noetl/commit/e71797a514a75c7f0a446bee4d0e1e507ba3b11f))

## [2.10.38](https://github.com/noetl/noetl/compare/v2.10.37...v2.10.38) (2026-03-24)

### Bug Fixes

* **runtime:** address PR review follow-ups ([3509394](https://github.com/noetl/noetl/commit/35093942ea424dedef1d4e9132ac1361027fa465))
* **server:** avoid false auto-resume recovery loops ([9ae0384](https://github.com/noetl/noetl/commit/9ae0384ad5bb1cf2df2a1ee54db515840fd9fa0d))
* **worker:** keep jetstream commands alive during execution ([89de91a](https://github.com/noetl/noetl/commit/89de91aae039c94942ce7db72e530fde030e4b51))

## [2.10.37](https://github.com/noetl/noetl/compare/v2.10.36...v2.10.37) (2026-03-24)

### Bug Fixes

* recover stale loop inflight saturation ([692598d](https://github.com/noetl/noetl/commit/692598d45a91b64abbe309276d3c214866b93e60))

## [2.10.36](https://github.com/noetl/noetl/compare/v2.10.35...v2.10.36) (2026-03-24)

### Bug Fixes

* stop inferring completion for active fallback status ([c1e4039](https://github.com/noetl/noetl/commit/c1e40392cd5b0fb57da42ce5523e5b84c0ad6cdf))

## [2.10.35](https://github.com/noetl/noetl/compare/v2.10.34...v2.10.35) (2026-03-24)

### Bug Fixes

* persist task sequence call.done before early return ([1521bb2](https://github.com/noetl/noetl/commit/1521bb2f0f178ff4fd08924ec20681a89c70f04f))
* persist task sequence continuation state ([5b9e612](https://github.com/noetl/noetl/commit/5b9e6126bf9cb4f26c2b38d78e10f12eb00e49cc))

## [2.10.34](https://github.com/noetl/noetl/compare/v2.10.33...v2.10.34) (2026-03-24)

### Bug Fixes

* auto-cancel inactive stuck executions ([f64f57c](https://github.com/noetl/noetl/commit/f64f57c2bf6bc02fc230e70e801cae7b3ecdcef7))
* guard reaper cancellation races ([4e20dfa](https://github.com/noetl/noetl/commit/4e20dfa102d62535243aac0121ab245aa3285f68))
* harden stuck execution reaper safety ([26ee21e](https://github.com/noetl/noetl/commit/26ee21ecaea5ec96dd3cb427d0a5ead9b74061d7))
* narrow stuck execution reaper selection ([de02e95](https://github.com/noetl/noetl/commit/de02e95bdc932b1b29e5c1a77a2755492ef185b1))

## [2.10.33](https://github.com/noetl/noetl/compare/v2.10.32...v2.10.33) (2026-03-24)

### Bug Fixes

* short-circuit repeated duplicate command notifications ([28af615](https://github.com/noetl/noetl/commit/28af615dee6adf81de9b74a5f083b3e1d342a84e))

## [2.10.32](https://github.com/noetl/noetl/compare/v2.10.31...v2.10.32) (2026-03-23)

### Bug Fixes

* ack duplicate active-claim notifications ([1b7b621](https://github.com/noetl/noetl/commit/1b7b621a2cd7177c4eb8a3929a557fe0e35bf321))
* clarify acked duplicate claim path ([f994c9b](https://github.com/noetl/noetl/commit/f994c9bb456c6c1708525f58ac986709ade57373))

## [2.10.31](https://github.com/noetl/noetl/compare/v2.10.30...v2.10.31) (2026-03-23)

### Bug Fixes

* fast recover stranded command notifications ([b327525](https://github.com/noetl/noetl/commit/b32752535719a2d63d7ae9948c42900c7e695a5b))
* harden fast publish recovery lifecycle ([b072e03](https://github.com/noetl/noetl/commit/b072e0361064322be3307c19e482712964d8ffa8))
* make initial command publish best effort ([c577cde](https://github.com/noetl/noetl/commit/c577cde466012587b266a9eedaab28c3499f434b))
* smooth fast publish recovery fanout ([77af3fc](https://github.com/noetl/noetl/commit/77af3fcc0632fb9150e6bf66c30c4080fc453c29))

## [2.10.30](https://github.com/noetl/noetl/compare/v2.10.29...v2.10.30) (2026-03-23)

### Bug Fixes

* harden nats publish recovery logging and reaper capacity ([2a6ef6d](https://github.com/noetl/noetl/commit/2a6ef6d340f55b3a7216fd52a4790385ea5f2057))
* preserve reaper recovery for long-running executions ([b6c4810](https://github.com/noetl/noetl/commit/b6c481068ce8bcfa92342b4a27c1b3b2b09383ec))
* prune reaper event scans by execution id window ([def791b](https://github.com/noetl/noetl/commit/def791b99504c034aa9764ad1d3650430953324a))
* recover stranded commands after nats publish interruptions ([cb98d38](https://github.com/noetl/noetl/commit/cb98d383655a141a7cbb17403d1307cdf97d40bf))
* reduce nats publish lock contention and unify reaper terminal events ([06894a2](https://github.com/noetl/noetl/commit/06894a2f390b055eaa2d366b2b72da92fc2b91df))
* reset stale nats publisher state before reconnect ([0d320cb](https://github.com/noetl/noetl/commit/0d320cb0f461d8fad3efa5da65d0f8e0a7867e49))

## [2.10.29](https://github.com/noetl/noetl/compare/v2.10.28...v2.10.29) (2026-03-23)

### Bug Fixes

* align pending command terminal events across apis ([5e34717](https://github.com/noetl/noetl/commit/5e347176c9abcace62f575865d4d92ae6435f81c))
* keep call.done from closing pending commands ([9acbdb8](https://github.com/noetl/noetl/commit/9acbdb8055fb2e9c78d1d32bb38c2e6ba0366fee))

## [2.10.28](https://github.com/noetl/noetl/compare/v2.10.27...v2.10.28) (2026-03-23)

### Bug Fixes

* clarify empty replayed loop collection logging ([ed7f272](https://github.com/noetl/noetl/commit/ed7f272045ce35aba0ba7eba498342d6df2cd71b))
* rerender loop collection when replay cache is empty ([596cad3](https://github.com/noetl/noetl/commit/596cad3e31ab89f28b662ecac0c22aeda35b2f7a))

## [2.10.27](https://github.com/noetl/noetl/compare/v2.10.26...v2.10.27) (2026-03-23)

### Bug Fixes

* invalidate stale cross-pod execution state cache ([5a71e3c](https://github.com/noetl/noetl/commit/5a71e3cc1b9a3869482af2774c30b777d8ce732a))

## [2.10.26](https://github.com/noetl/noetl/compare/v2.10.25...v2.10.26) (2026-03-23)

### Bug Fixes

* restore replayed set_ctx state from persisted events ([d408ff6](https://github.com/noetl/noetl/commit/d408ff60ecb791e9f86b807a279cc82a0611072c))

## [2.10.25](https://github.com/noetl/noetl/compare/v2.10.24...v2.10.25) (2026-03-23)

### Bug Fixes

* preserve ctx and iter dict lookup in render templates ([1955d6f](https://github.com/noetl/noetl/commit/1955d6f46e683d46637cd915fc8d2e96eb282091))

## [2.10.24](https://github.com/noetl/noetl/compare/v2.10.23...v2.10.24) (2026-03-23)

### Bug Fixes

* paginate execution list queries and bound ui fetches ([a965260](https://github.com/noetl/noetl/commit/a9652601ac7b3bf7d68b0c9806caeba5450aef02))
* stabilize execution list pagination ordering ([5dfdc73](https://github.com/noetl/noetl/commit/5dfdc73fcb68767fe9bb8351ef3f7ea16db99e0c))

## [2.10.23](https://github.com/noetl/noetl/compare/v2.10.22...v2.10.23) (2026-03-23)

### Bug Fixes

* align execution list status with terminal inference ([75eec20](https://github.com/noetl/noetl/commit/75eec20d34c7247f22687f20d8908b9e86ebbad3))

## [2.10.22](https://github.com/noetl/noetl/compare/v2.10.21...v2.10.22) (2026-03-23)

### Bug Fixes

* clamp running execution durations in ui ([409520b](https://github.com/noetl/noetl/commit/409520bd0d0ab18ef2eb7ffd3cdcdf4e807c870e))
* normalize execution status counters in ui ([eeded19](https://github.com/noetl/noetl/commit/eeded19f6355c20e559dbc130f167a5762d10ca1))
* normalize execution status stats in ui ([171b5e2](https://github.com/noetl/noetl/commit/171b5e200fec6f184c945d28848ac7c9d9e22ff0))
* prevent loop transition event handler crash ([428eacd](https://github.com/noetl/noetl/commit/428eacdac7f6d6aec65144750bb4eb68af4d6ce9))
* prevent stuck local executions on worker and terminal transitions ([73de8df](https://github.com/noetl/noetl/commit/73de8df654ef7e831c50012e70136864e78b82b9))
* reduce duplicate execution event fetches ([15b221f](https://github.com/noetl/noetl/commit/15b221f9263c7f9000862538fcd04934dfe3cae9))
* resolve full payloads for result refs ([c5ca431](https://github.com/noetl/noetl/commit/c5ca431b6dc2bf3b6c62aece58ffd014c881c820))
* split execution events api and align ui consumers ([34c48eb](https://github.com/noetl/noetl/commit/34c48eb712e1f24af069f94892c82e0f77f3c650))
* unwrap persisted event payloads for engine rendering ([280e7fe](https://github.com/noetl/noetl/commit/280e7fe7156172378df2f7cebd68eb4ea55a1bdd))

## [2.10.21](https://github.com/noetl/noetl/compare/v2.10.20...v2.10.21) (2026-03-23)

### Bug Fixes

* align server leases with runtime schema ([50cd421](https://github.com/noetl/noetl/commit/50cd4213dcad6177100981776215421f8236bfc2))
* coordinate server control loops and externalize oversized payloads ([f5af6dd](https://github.com/noetl/noetl/commit/f5af6dd2e696673cc9908bf420cb8f6da95c4915))

## [2.10.20](https://github.com/noetl/noetl/compare/v2.10.19...v2.10.20) (2026-03-23)

### Bug Fixes

* keep repeated batch executions running until all commands finish ([1127650](https://github.com/noetl/noetl/commit/11276500db9c3361bfc57c4ead9b17bc7e1e967d))
* share pending command query across execution endpoints ([8edbd32](https://github.com/noetl/noetl/commit/8edbd32d3bc069f78346d7573fbe822a685d4e37))

## [2.10.19](https://github.com/noetl/noetl/compare/v2.10.18...v2.10.19) (2026-03-22)

### Bug Fixes

* align execution detail status with terminal inference ([a8808fe](https://github.com/noetl/noetl/commit/a8808fe0854e984a09c866561469c6eb3f302fdb))
* scope execution pending inference and cover terminal precedence ([fac632d](https://github.com/noetl/noetl/commit/fac632db8ee689034b679b46ac4fbc158359d3a9))

## [2.10.18](https://github.com/noetl/noetl/compare/v2.10.17...v2.10.18) (2026-03-21)

### Bug Fixes

* make command_id claim lookups index-friendly ([6bab567](https://github.com/noetl/noetl/commit/6bab5676cc2abf35462c7ce7fce30564563fad0b))
* normalize non-terminal completed events as running ([e75465f](https://github.com/noetl/noetl/commit/e75465f345ff0e998234de12e6cfbb7eb709cf60))
* refactor command_id lookups and lock SQL regression shape ([a602824](https://github.com/noetl/noetl/commit/a602824416760508dac2f3b35bb3299e0213d210))

## [2.10.17](https://github.com/noetl/noetl/compare/v2.10.16...v2.10.17) (2026-03-21)

### Bug Fixes

* address copilot review feedback for PR 288 ([09de614](https://github.com/noetl/noetl/commit/09de614049daeffb8350c33b0c0920eda4437c22))
* harden db outage recovery and bound postgres memory pressure ([9963552](https://github.com/noetl/noetl/commit/996355255e33cef7aa230e96e33979fdf4dd6970))

## [2.10.16](https://github.com/noetl/noetl/compare/v2.10.15...v2.10.16) (2026-03-20)

### Bug Fixes

* address copilot feedback for regression event paging and mock config ([f6dbde9](https://github.com/noetl/noetl/commit/f6dbde9740d833e15070af043d24ce2c3da5ab25))
* harden command reaper matching and stabilize kind regression harness ([62342d2](https://github.com/noetl/noetl/commit/62342d254427b52bbc4053e8c0ec53cf5dc9ba72))

## [2.10.15](https://github.com/noetl/noetl/compare/v2.10.14...v2.10.15) (2026-03-19)

### Bug Fixes

* address copilot feedback for PR 285 loop watchdog and postgres retry ([7de6e8c](https://github.com/noetl/noetl/commit/7de6e8c9803671fcf170219ba9bca2d99e3661f4))
* recover stalled loops and retry transient postgres connection drops ([f9b47fc](https://github.com/noetl/noetl/commit/f9b47fc1415ff2d63aa0f2ba777d5809d60e6ac8))

## [2.10.14](https://github.com/noetl/noetl/compare/v2.10.13...v2.10.14) (2026-03-19)

### Bug Fixes

* stabilize reference-chain stress harness and page reduction flow ([de4f2aa](https://github.com/noetl/noetl/commit/de4f2aa43dd0bf63c2f9b1bc5d039149367d626b))

## [2.10.13](https://github.com/noetl/noetl/compare/v2.10.12...v2.10.13) (2026-03-19)

### Bug Fixes

* add neutral paginated loop stress harness ([1aa7c4e](https://github.com/noetl/noetl/commit/1aa7c4ead7445a935ed46b04a7974f16a549aa3a))
* address copilot feedback for stress harness polling and guards ([475428a](https://github.com/noetl/noetl/commit/475428ae13fc3f3e7597748cff465b4db7dcb0f7))
* harden stress harness status polling and chain bounds ([8a7a9de](https://github.com/noetl/noetl/commit/8a7a9de5a18669aeb2a284e75060757693dcdaea))
* include underscore lifecycle events in stress status query ([155d2fa](https://github.com/noetl/noetl/commit/155d2fa0d2d48209b569aca7e0b947e762788752))

## [2.10.12](https://github.com/noetl/noetl/compare/v2.10.11...v2.10.12) (2026-03-19)

### Bug Fixes

* bound loop replay state and completion counters ([fa604fe](https://github.com/noetl/noetl/commit/fa604fe5ff98c484f67acc017db42a1e050eef45))

## [2.10.11](https://github.com/noetl/noetl/compare/v2.10.10...v2.10.11) (2026-03-18)

### Bug Fixes

* guard loop continuation from mutable ctx and add regression test ([238d3a4](https://github.com/noetl/noetl/commit/238d3a490a111469f118846cae9b2420dff712ca))
* snapshot loop collections to prevent in-place mutation bleed ([f0ca292](https://github.com/noetl/noetl/commit/f0ca292a2caa3011c3e4c4a1b3d49c32e5724fd2))

## [2.10.10](https://github.com/noetl/noetl/compare/v2.10.9...v2.10.10) (2026-03-18)

### Bug Fixes

* infer terminal status from batch completion with no pending commands ([123e2dc](https://github.com/noetl/noetl/commit/123e2dcbed49653646744a98c3f1196863d7fabf))

## [2.10.9](https://github.com/noetl/noetl/compare/v2.10.8...v2.10.9) (2026-03-18)

### Bug Fixes

* resolve stale execution status from terminal event precedence ([4abbaa5](https://github.com/noetl/noetl/commit/4abbaa5efe48e277ea5ca06ee6fe1dd174facfe5))

## [2.10.8](https://github.com/noetl/noetl/compare/v2.10.7...v2.10.8) (2026-03-18)

### Bug Fixes

* address latest copilot review findings on pr271 ([bd2bd97](https://github.com/noetl/noetl/commit/bd2bd971573dcb3acf22a779bab72187785c2c8d))
* finalize stuck executions and close dead-end next routes ([cb5ee38](https://github.com/noetl/noetl/commit/cb5ee382eb6790407cc5faf4031a277c8e28d004))
* resolve latest copilot findings on pr271 ([032d1af](https://github.com/noetl/noetl/commit/032d1af71b301ff95b8f6338997331282fd1d7ad))
* reuse next routing match result in completion check ([aedb883](https://github.com/noetl/noetl/commit/aedb8834dc1bcda9a18e392d3e10a5407f28409f))
* trigger release for finalize dead-end patch ([29e056d](https://github.com/noetl/noetl/commit/29e056d0729cfa12c9c04e11b9322dde1e7a28b6))

## [2.10.7](https://github.com/noetl/noetl/compare/v2.10.6...v2.10.7) (2026-03-18)

### Bug Fixes

* centralize server URL normalization helpers ([62a6830](https://github.com/noetl/noetl/commit/62a6830929dbf9c7df1c60e5c13be974b657b21b))
* normalize repeated /api suffixes in server URL handling ([10552aa](https://github.com/noetl/noetl/commit/10552aa67f47db8c9cdb430a15ba0b48096e10c2))
* normalize server URL handling to prevent /api/api worker calls ([f70d397](https://github.com/noetl/noetl/commit/f70d3971cefb8433e99f287e51095ea634da445a))

## [2.10.6](https://github.com/noetl/noetl/compare/v2.10.5...v2.10.6) (2026-03-17)

### Bug Fixes

* address copilot review findings for pr266 ([15e9466](https://github.com/noetl/noetl/commit/15e946690e2f32f3a0dcc032dc982425ffd25136))
* address latest copilot validation findings ([722d514](https://github.com/noetl/noetl/commit/722d5148bddea37169cb0944c776b9cdd9099b8f))
* clamp claim cache ttl and harden config parsing ([7821978](https://github.com/noetl/noetl/commit/782197831bc68e835c05710510c5846b5efb5023))
* desynchronize active-claim retries and clarify retry logs ([acf9a65](https://github.com/noetl/noetl/commit/acf9a65da62b4ebb8fe29ac5bfd49cf1ea60ca07))
* **runtime:** harden claim retries, timeouts, and active-claim caching ([8b3e28e](https://github.com/noetl/noetl/commit/8b3e28e96b2f5d2c3dd46183bdd1da8fa3d00b9d))

## [2.10.5](https://github.com/noetl/noetl/compare/v2.10.4...v2.10.5) (2026-03-15)

### Bug Fixes

* address copilot review on cache limits and tracker index ([de48f43](https://github.com/noetl/noetl/commit/de48f43ce88d1851de721fd0daeda03d8be162d1))
* address follow-up copilot cleanup and tracker concerns ([212565e](https://github.com/noetl/noetl/commit/212565edaef8ac0416657416f78cf59ead2cf5dd))
* bound temp store caches and track worker refs ([0e283dd](https://github.com/noetl/noetl/commit/0e283ddfa1cbcbe4c39ebd9f4b01bc78733e1a42))

## [2.10.4](https://github.com/noetl/noetl/compare/v2.10.3...v2.10.4) (2026-03-11)

### Bug Fixes

* add amadeus ai token smoke fixture playbook ([582ca10](https://github.com/noetl/noetl/commit/582ca102ed6dfb7771cb717986d71c6e20a9028a))
* add command reaper to recover commands orphaned by OOMKill/SIGKILL ([b7dbe6e](https://github.com/noetl/noetl/commit/b7dbe6e9f80feaf837abdd272156dc475ffaf114))

## [2.10.3](https://github.com/noetl/noetl/compare/v2.10.2...v2.10.3) (2026-03-06)

### Bug Fixes

* add agent runtime bridge and catalog agent discovery endpoints ([896864b](https://github.com/noetl/noetl/commit/896864b06e733adae1fc25613a37472f15f93a58))
* remove in-repo automation and switch operational references to ops ([cac24c7](https://github.com/noetl/noetl/commit/cac24c7de9502e8d08c61d5c2e6ffe7f6595b10c))

## [2.10.2](https://github.com/noetl/noetl/compare/v2.10.1...v2.10.2) (2026-03-05)

### Bug Fixes

* invalidate stale execution cache when command issuance fails ([2c7bf66](https://github.com/noetl/noetl/commit/2c7bf6699d64fdfdd8f9d5889f2a976cb088a763))

## [2.10.1](https://github.com/noetl/noetl/compare/v2.10.0...v2.10.1) (2026-03-05)

### Bug Fixes

* **worker:** retry transient sub-playbook HTTP failures ([6fbf00e](https://github.com/noetl/noetl/commit/6fbf00ef6366c757943b2ed6ac086d1cffb82953))

## [2.10.0](https://github.com/noetl/noetl/compare/v2.9.0...v2.10.0) (2026-03-05)

### Features

* **server:** readiness-gated playbook recovery on startup ([40d42be](https://github.com/noetl/noetl/commit/40d42beb0758d49d4b50fd598fac972c3ceb9755))

### Bug Fixes

* **logging:** suppress health and pool-status access log flood ([71b5e7a](https://github.com/noetl/noetl/commit/71b5e7ab1bceb60e28334bbcb05a21102ded7dc0))

## [2.9.0](https://github.com/noetl/noetl/compare/v2.8.9...v2.9.0) (2026-03-05)

### Features

* **server:** async batch acceptance with request_id tracking ([b4a18e1](https://github.com/noetl/noetl/commit/b4a18e1eb9b9d45736ef92b1d254bd50e1e90968))

## [2.8.9](https://github.com/noetl/noetl/compare/v2.8.8...v2.8.9) (2026-03-04)

### Bug Fixes

* add distributed-claim regression playbooks and remove legacy crates workspace ([f8e380b](https://github.com/noetl/noetl/commit/f8e380b8647a22095912fc277ad713f7183922b3))
* address PR247 copilot path and build-context issues ([7973b70](https://github.com/noetl/noetl/commit/7973b70dd4c088c20bea39f92a25f59ae02fa907))

## [2.8.8](https://github.com/noetl/noetl/compare/v2.8.7...v2.8.8) (2026-03-03)

### Bug Fixes

* add new testing playbooks for longtime batches ([3758f41](https://github.com/noetl/noetl/commit/3758f41bcc06f27b1bdfa3d7f3023adb29e3a931))
* **claim:** avoid reclaiming healthy long-running worker commands ([b8b699b](https://github.com/noetl/noetl/commit/b8b699b6dc1f2925c1087a8bf469c5e894046c4b))
* **claim:** reject same-worker duplicate command while running ([c67674b](https://github.com/noetl/noetl/commit/c67674bcd724c0201224f413d52ad772ed2d6134))

## [2.8.7](https://github.com/noetl/noetl/compare/v2.8.6...v2.8.7) (2026-03-01)

### Bug Fixes

* execution status retrieval and optimize batch processing ([14a7903](https://github.com/noetl/noetl/commit/14a79039201f7ea7b69aa50adf35febf16e6dd93))
* execution status with duration metrics and human-readable format ([9cb0cdc](https://github.com/noetl/noetl/commit/9cb0cdce886c52dea1d5b03cd8b1beded20a627c))

## [2.8.6](https://github.com/noetl/noetl/compare/v2.8.5...v2.8.6) (2026-02-28)

### Bug Fixes

* Add deployment and service configuration for paginated API in GKE ([87c424d](https://github.com/noetl/noetl/commit/87c424d07b1990eabe3349cd9a6d0871ab52feee))
* add SINK_REFERENCES_ENABLED env var to toggle HTTP response reference wrapping ([b61584d](https://github.com/noetl/noetl/commit/b61584d28b97f7843d6c21c153a5905422c2a3bd))
* Add tests for NATSCommandSubscriber and TempStore functionality ([89b9a95](https://github.com/noetl/noetl/commit/89b9a9564f0acce35aa136dc40347c1006ce778a))
* auto-resume functionality and improve Postgres pool management ([b62b94a](https://github.com/noetl/noetl/commit/b62b94ac36c82968bcb5c1af10a6291980c3727e))
* end step handling ([c8b911c](https://github.com/noetl/noetl/commit/c8b911cbb6f012c74bf46e10055c7a162fb4f52d))
* event handling and credential fetching in the worker ([9e66e13](https://github.com/noetl/noetl/commit/9e66e137c76e02a61e1fee8cf20dc1f0792007f0))
* Implement adaptive concurrency control for worker-server communication ([3963bea](https://github.com/noetl/noetl/commit/3963bead16bed9abb92b9ea626bf2697116e7ddd))
* loop execution with max_in_flight control and parallel dispatch ([e3ec10a](https://github.com/noetl/noetl/commit/e3ec10a0e193b710a19c56493d986473a9076f2a))
* optimize Postgres configuration and enhance async task execution ([55368ce](https://github.com/noetl/noetl/commit/55368ce750f5439c59b2e4aa6113b10c5fb93bd6))
* parallel chunk-worker stress test with engine LOOP-CALL.DONE fix and full payload storage ([d1fc390](https://github.com/noetl/noetl/commit/d1fc3905a54c01d13cfb65336c9a2058a5bf4520))
* parallel chunk-worker stress test with engine LOOP-CALL.DONE fix and full payload storage ([dfca19e](https://github.com/noetl/noetl/commit/dfca19ed70342a9cb4a1c3b919887f9da9b4e78d))
* reduce items_max_in_flight to improve resource management in stress tests ([0697e47](https://github.com/noetl/noetl/commit/0697e4714044b5e4c2d3248de6b8b69687e895c8))
* Refactor batch processing playbooks to enhance error handling and memory management ([e5dd34e](https://github.com/noetl/noetl/commit/e5dd34e343b8384d21882059aec3965b91ed5dee))
* task sequence handling and add terminal event emissions for command failures ([b776e23](https://github.com/noetl/noetl/commit/b776e23b0df78ca03f29251b7da8f2cc961efc17))
* Update dependencies and enhance Auth0 integration with new configuration options ([adf8ef7](https://github.com/noetl/noetl/commit/adf8ef75dde2c095cb028f2679552269815b4df6))
* update max_in_flight in server OOM stress chunk worker to a static value ([ef6cdb4](https://github.com/noetl/noetl/commit/ef6cdb4807cfce7f04379d978e9f6feb5257eaea))

## [2.8.5](https://github.com/noetl/noetl/compare/v2.8.4...v2.8.5) (2026-02-24)

### Bug Fixes

* enhance loop handling and terminal status detection in playbook execution ([7acf458](https://github.com/noetl/noetl/commit/7acf458b327a412ca694865ae14b922ae746cf5d))
* improve execution status handling and add tests for status endpoint ([c3fe7e4](https://github.com/noetl/noetl/commit/c3fe7e4553ff2cb48c7b8e392bec0487439b8b37))

## [2.8.4](https://github.com/noetl/noetl/compare/v2.8.3...v2.8.4) (2026-02-20)

### Bug Fixes

* Add AI analysis endpoint for execution triage ([c70cfb2](https://github.com/noetl/noetl/commit/c70cfb2e0800541a1d809246aac683181e2e5dca))
* Add execution analysis request and response schemas ([3b814f3](https://github.com/noetl/noetl/commit/3b814f3542488bf73e1c05add276d014ec9e01a4))
* add Playbook Test Lab component for managing and executing test suites ([3ecf63d](https://github.com/noetl/noetl/commit/3ecf63d9bce9d4ad925a4dbdc16b7f309f902438))
* add React example for NoETL Gateway with Amadeus integration ([0a9f081](https://github.com/noetl/noetl/commit/0a9f081fb2f6c69c1efa0a2b348f6899034098f6))
* enhance callback handling and execution polling in Amadeus integration example ([5f7071e](https://github.com/noetl/noetl/commit/5f7071e386a80e0e8af228822ed9adfd784f86cb))
* Enhance user management and role handling ([cf5b6b8](https://github.com/noetl/noetl/commit/cf5b6b8762476c2401756d4cec8ee15083334730))
* implement AI-driven playbook generation and explanation features ([90f86b0](https://github.com/noetl/noetl/commit/90f86b0927728811bfd6b7c3c3eccf991fcdec10))
* update README and enhance health probe diagnostics in React example ([9bfd703](https://github.com/noetl/noetl/commit/9bfd703e903ac7c3502644de2f6bb03ca00f3f5d))

## [2.8.3](https://github.com/noetl/noetl/compare/v2.8.2...v2.8.3) (2026-02-10)

### Bug Fixes

* Refactor playbook variable handling and update DSL to v2 ([84e77b0](https://github.com/noetl/noetl/commit/84e77b0df054881b68d94b0d141f5465bae723ba))

## [2.8.2](https://github.com/noetl/noetl/compare/v2.8.1...v2.8.2) (2026-02-09)

### Bug Fixes

* enhance task result handling and logging for improved context management ([aaba409](https://github.com/noetl/noetl/commit/aaba40998cd4c3e6728ab5d9419a84b4bdd6f390))

## [2.8.1](https://github.com/noetl/noetl/compare/v2.8.0...v2.8.1) (2026-02-09)

### Bug Fixes

* convert single tool steps with policy rules to task sequence format for enhanced control flow ([7607a01](https://github.com/noetl/noetl/commit/7607a011ac0cf4c113f49adbebd4769dafcddde4))
* enhance command step handling for task sequences with metadata support ([29f9425](https://github.com/noetl/noetl/commit/29f94258734275514759704bb13602ba0ee87dd4))
* enhance PostgreSQL connection pool initialization for improved concurrency support ([5fec0e1](https://github.com/noetl/noetl/commit/5fec0e15e560936281749ae19f785061d45b83a2))
* enhance task sequence execution with context mutation and loop handling ([7a288f1](https://github.com/noetl/noetl/commit/7a288f1ed19eb12679f856a25b65689ca277c342))
* improve template rendering with fallback to ast.literal_eval for Python repr format ([4230428](https://github.com/noetl/noetl/commit/4230428b809ba4551cb798f6643d891a766759b6))
* streamline PostgreSQL auth configuration in pagination test playbook ([dad7bb5](https://github.com/noetl/noetl/commit/dad7bb5c4fad33a841423ef5735f27b7342fd1c4))
* unwrap single-task sequence results for backward compatibility with templates ([e5ad99d](https://github.com/noetl/noetl/commit/e5ad99df00ead852fb915739ffb0e174f9aefc52))

## [2.8.0](https://github.com/noetl/noetl/compare/v2.7.5...v2.8.0) (2026-02-08)

### Features

* Add canonical v2 workflow entry, routing, and termination semantics ([de0c1f7](https://github.com/noetl/noetl/commit/de0c1f738e606531290452f44f4d8b530e1a3f34))
* Add NATS tool for JetStream, K/V Store, and Object Store operations ([ad49bee](https://github.com/noetl/noetl/commit/ad49bee4d0acf9aff758d926846ea8771f32639f))
* Enhance gateway deployment with CORS support and NATS configuration; add context API and server-side rendering in executor ([f1d6ed3](https://github.com/noetl/noetl/commit/f1d6ed3fa0da9f39d8950cb87e67b12591fcbcee))
* Implement NATS-based callback system for async playbook execution results and enhance auth middleware with callback support ([d287e1d](https://github.com/noetl/noetl/commit/d287e1da89bee1433a409ff9051a1263a2599314))
* Implement PipelineExecutor with error handling and control flow ([f7624bf](https://github.com/noetl/noetl/commit/f7624bf68ba35adc1df2644e176a5d4f28dacb61))
* Implement storage backends for NoETL ResultStore ([b872324](https://github.com/noetl/noetl/commit/b872324bf1efc9955b6650977ab5120aec066c5e))
* Refactor workflow steps to enhance routing and add secret creation for NoETL deployment ([fe268eb](https://github.com/noetl/noetl/commit/fe268eb27ad0f947b3f54f24b981e493296f472e))
* Update workflow to ensure DB tables exist for Amadeus AI events and results ([3fe2115](https://github.com/noetl/noetl/commit/3fe211554a3c8b9ffaffdf666cab2696313cd207))

### Bug Fixes

* add auto-resume logic on restarts for noetl server ([2eac632](https://github.com/noetl/noetl/commit/2eac632d6a09efaa72bf2a437d9fb756298bd3b4))
* add TempStore service for managing TempRef storage operations ([3c9753e](https://github.com/noetl/noetl/commit/3c9753eb1663b6dc6236068aa0460ecac0442f62))
* Enhance Amadeus AI API integration with improved workflow steps and add test playbook ([0bd59b3](https://github.com/noetl/noetl/commit/0bd59b3e411dea45d705109f1928f257d3f3e108))
* enhance execution status checks to include cancellation and improve auto-resume logic ([e09a22d](https://github.com/noetl/noetl/commit/e09a22d922c89d7b6ffd614154b088bcb8856c8d))
* implement atomic command claiming and fetching via new endpoint ([93cfd9f](https://github.com/noetl/noetl/commit/93cfd9f115a465c378c53df5f8a429bc12c9b92b))
* implement connection hub for managing client SSE and WebSocket connections ([f7c43a9](https://github.com/noetl/noetl/commit/f7c43a949db1be9e12a1644be52ad1be5a902eb9))
* Implement NATS tool support for K/V Store operations and add test playbook ([790f822](https://github.com/noetl/noetl/commit/790f822a3753acb9a42e72d3e2d5f5fe6decd3f3))
* improve kind cluster check and port management logic in bootstrap workflow ([f0022b4](https://github.com/noetl/noetl/commit/f0022b4cbcbc2d3b5b3b4610fdaa8702bdefce72))
* Refactor documentation and code for Canonical v10 updates ([bbeba8e](https://github.com/noetl/noetl/commit/bbeba8e5c3a5ff95c4ca1af699e10a9eb91ca0d1))
* refactor playbook conditionals from next: with when to case: pattern ([d1ded12](https://github.com/noetl/noetl/commit/d1ded126c5b5c30c2fdb32a6ffbd3d6b4ce98740))
* refactor playbook steps for improved clarity and execution flow ([9e80468](https://github.com/noetl/noetl/commit/9e80468979189230716cbace7065fd4aae1d1e75))
* Replace 'ctx' with 'workload' in Auth0 playbooks for consistency ([f900a72](https://github.com/noetl/noetl/commit/f900a721bedb254bfa02c0813d63645b95ea52e6))
* Replace 'sink' actions with 'send_callback' in Auth0 playbooks for error handling ([369ec34](https://github.com/noetl/noetl/commit/369ec340020a91883a7580e098a9647a110b4cf8))
* TempStore service for managing temporary data storage ([fb171e4](https://github.com/noetl/noetl/commit/fb171e4f31764f0020f65f4dfa8d9436f6f2cf86))
* Update workload variable handling in Playbook and YAML configuration for Auth0 integration ([2101292](https://github.com/noetl/noetl/commit/2101292f226bab069f3c244f03dbf94205bbf001))

## [2.7.5](https://github.com/noetl/noetl/compare/v2.7.4...v2.7.5) (2026-02-02)

### Bug Fixes

* enhance execution status checks to include cancellation and improve auto-resume logic ([996248c](https://github.com/noetl/noetl/commit/996248cba6984d98ca640d884bc8e93d60c6249b))

## [2.7.4](https://github.com/noetl/noetl/compare/v2.7.3...v2.7.4) (2026-02-02)

### Bug Fixes

* add auto-resume logic on restarts for noetl server ([5afcedf](https://github.com/noetl/noetl/commit/5afcedf3b7fc4b174a39c2b85ed19e04836f94b6))

## [2.7.3](https://github.com/noetl/noetl/compare/v2.7.2...v2.7.3) (2026-01-28)

### Bug Fixes

* Enhance playbook execution with versioning support and improve UI for playbook selection ([877f667](https://github.com/noetl/noetl/commit/877f66760395ef7f29e5d5bd274326ee0e588fd6))
* Update API request parameters for NoETL execution ([f01f475](https://github.com/noetl/noetl/commit/f01f4750dc430c3e60a526f91a61a5beb0be4087))

## [2.7.2](https://github.com/noetl/noetl/compare/v2.7.1...v2.7.2) (2026-01-27)

### Bug Fixes

* Logs ([2067e03](https://github.com/noetl/noetl/commit/2067e0322d64a42edbbd9834145e03c9ee4171bb))

## [2.7.1](https://github.com/noetl/noetl/compare/v2.7.0...v2.7.1) (2026-01-26)

### Bug Fixes

* note deprecated cli ([#225](https://github.com/noetl/noetl/issues/225)) ([48b9962](https://github.com/noetl/noetl/commit/48b9962a59806cccc93293af9125d5832d59f19e))

## [2.7.0](https://github.com/noetl/noetl/compare/v2.6.0...v2.7.0) (2026-01-26)

### Features

* add Cloud Build support for GKE deployment and noetl-tools crate ([7d6458f](https://github.com/noetl/noetl/commit/7d6458f70845c6a9e000684c2496766a958cf20e))

### Bug Fixes

* decouple schema init from postgres deployment and add gateway public endpoint ([f906c16](https://github.com/noetl/noetl/commit/f906c16b97125ffe3f8801f761c4f926feda0e34))

## [2.6.0](https://github.com/noetl/noetl/compare/v2.5.12...v2.6.0) (2026-01-23)

### Features

* Dummy chagnes to trigger GitHub Actions ([6aae66f](https://github.com/noetl/noetl/commit/6aae66f94e0a61c2b2cdba455d1ef01943b1e317))

## [2.5.12](https://github.com/noetl/noetl/compare/v2.5.11...v2.5.12) (2026-01-22)

### Bug Fixes

* increase timeout limits for noetl worker http ([#215](https://github.com/noetl/noetl/issues/215)) ([5cccd62](https://github.com/noetl/noetl/commit/5cccd620cab2110809a190a1caa794e04813a648))

## [2.5.11](https://github.com/noetl/noetl/compare/v2.5.10...v2.5.11) (2026-01-21)

### Bug Fixes

* bump noetl versions 2.5.11 ([#213](https://github.com/noetl/noetl/issues/213)) ([c6aa17f](https://github.com/noetl/noetl/commit/c6aa17f72a7f4993aedeb0b0511fd3af5dea452a))

## [2.5.10](https://github.com/noetl/noetl/compare/v2.5.9...v2.5.10) (2026-01-21)

### Bug Fixes

* Make dummy changes in Dockerfile ([f5d2825](https://github.com/noetl/noetl/commit/f5d2825f2e9862d3d3b1a8f5223601118dce6d6f))

## [2.5.9](https://github.com/noetl/noetl/compare/v2.5.8...v2.5.9) (2026-01-20)

### Bug Fixes

* Make dummy changes in Dockerfile NOETL-6 ([7968ed7](https://github.com/noetl/noetl/commit/7968ed7f14f1c740381abbce9d09a63d0e5d246d))

## [2.5.8](https://github.com/noetl/noetl/compare/v2.5.7...v2.5.8) (2026-01-18)

### Bug Fixes

* implement hybrid case evaluation with server variable fetching ([76dbe64](https://github.com/noetl/noetl/commit/76dbe6445bd14d486709587da101fe7804bebef4))
* update execution request schema to use 'args' instead of 'parameters' for consistency ([44c0d3c](https://github.com/noetl/noetl/commit/44c0d3c0d52c1c1993b11b076dda390df20c8d84))

## [2.5.7](https://github.com/noetl/noetl/compare/v2.5.6...v2.5.7) (2026-01-16)

### Bug Fixes

* update NATS K/V key format to use dots instead of colons ([#208](https://github.com/noetl/noetl/issues/208)) ([36e56b0](https://github.com/noetl/noetl/commit/36e56b053dda65c08ca65a6306977bf9cd6621fb))

## [2.5.6](https://github.com/noetl/noetl/compare/v2.5.5...v2.5.6) (2026-01-15)

### Bug Fixes

* google id token handler ([#207](https://github.com/noetl/noetl/issues/207)) ([515ea16](https://github.com/noetl/noetl/commit/515ea163430e28ca839e435ea3d02fc31edbe28f))
* update SHA256 for v2.5.5 after tag recreation ([5c45121](https://github.com/noetl/noetl/commit/5c45121ed7d0f224cc1da369297bb352aaca9a37))

## [2.5.5](https://github.com/noetl/noetl/compare/v2.5.4...v2.5.5) (2026-01-11)

### Bug Fixes

* add auto-discovery and file resolution for noetl run command ([02d09e3](https://github.com/noetl/noetl/commit/02d09e3e8d9ea37b5346006661454acc223d6e5e))
* reduce logging footprint - move verbose logs to debug level ([9f612c1](https://github.com/noetl/noetl/commit/9f612c1379437e58371225e2c6a1bde4e64bf4da))
* rename schema field in SnowflakeFieldMapping to avoid Pydantic warning ([ca2ffe6](https://github.com/noetl/noetl/commit/ca2ffe61430c617aa2000e847e0e1d1607cfec56))
* simplify developer experience with complete bootstrap improvements ([88f49f4](https://github.com/noetl/noetl/commit/88f49f4b96dbe3721469005d941a1b554c8e55b0))

## [2.5.3](https://github.com/noetl/noetl/compare/v2.5.2...v2.5.3) (2026-01-10)

### Bug Fixes

* add local playbook execution to noetlctl CLI ([b46ba98](https://github.com/noetl/noetl/commit/b46ba98666f715603c43c9880d9e4506c74ec101))

## [2.5.2](https://github.com/noetl/noetl/compare/v2.5.1...v2.5.2) (2026-01-07)

### Bug Fixes

* Add per-action PostgreSQL pool configuration and Python tool documentation ([57b1cfa](https://github.com/noetl/noetl/commit/57b1cfa965c0988ad8fc9ad5aa38dc2487b25f9b))

## [2.5.1](https://github.com/noetl/noetl/compare/v2.5.0...v2.5.1) (2026-01-07)

### Bug Fixes

* improve worker performance and eliminate pool timeout errors ([9f7d749](https://github.com/noetl/noetl/commit/9f7d749263169f96054eedfd83a851265cede218))

## [2.5.0](https://github.com/noetl/noetl/compare/v2.4.0...v2.5.0) (2026-01-05)

### Features

* Phase 1 - Rename noetlctl to noetl and add server/worker/db management commands ([9b404ef](https://github.com/noetl/noetl/commit/9b404ef339189068cc05878ea9543d4a1154535e))
* remove Python CLI and complete Rust CLI migration (Phase 3) ([6823d3d](https://github.com/noetl/noetl/commit/6823d3d5a768c0176a15899df0956888092c8ef0))

### Bug Fixes

* add POLARS_SKIP_CPU_CHECK to bypass ARM64 emulation issues ([466af60](https://github.com/noetl/noetl/commit/466af60d8d34658b1155315643c71af6f2e9096f))
* resolve Rust CLI compilation warnings and Docker deployment issues ([957a545](https://github.com/noetl/noetl/commit/957a545d097e6a1739fdde56061750f56140886d))
* update worker __init__.py to export v2 functions only ([0e340a1](https://github.com/noetl/noetl/commit/0e340a11a22d7ae8584b2bf99f393f561de6793a))
* update worker _emit_event to use broker API schema (event_type, node_name) ([b9dae7c](https://github.com/noetl/noetl/commit/b9dae7cc95ffe09f55c5ed75f767f3c7a2a38d0f))
* use /api/events endpoint (not /api/v2/events) ([c618971](https://github.com/noetl/noetl/commit/c6189716c92fc7c4eb7d3c24bcbb1dae6444150d))
* use /api/v2/events endpoint with original dot-separated event names ([bf488dd](https://github.com/noetl/noetl/commit/bf488dd8311cc23196a6ace9c825e25158719f7a))

## [2.4.0](https://github.com/noetl/noetl/compare/v2.3.3...v2.4.0) (2025-12-31)

### Features

* add comprehensive PostgreSQL to Excel to GCS pipeline test ([09bc909](https://github.com/noetl/noetl/commit/09bc909846d99cc85511b438f8ff682b617d9210))

### Bug Fixes

* add GCS plugin for file upload tasks ([1842076](https://github.com/noetl/noetl/commit/1842076d6b4f91091a75b30e30eb7bcf05e18c3d))
* document postgres excel gcs troubleshooting ([b2c0138](https://github.com/noetl/noetl/commit/b2c01389cc93fb1cc347ccd0b8e00103ce5f178b))
* excel handling ([be435ff](https://github.com/noetl/noetl/commit/be435ff4eb6bedde18ec482734d1d670c610c3ca))

## [2.3.3](https://github.com/noetl/noetl/compare/v2.3.2...v2.3.3) (2025-12-26)

### Bug Fixes

* remove expired job reclamation logic ([98a9b55](https://github.com/noetl/noetl/commit/98a9b55516ab0b44d4358cebde5dce4a0099fc30))

## [2.3.2](https://github.com/noetl/noetl/compare/v2.3.1...v2.3.2) (2025-12-26)

### Bug Fixes

* remove deprecated NoETL core modules and .gitignore entries ([cbcfb73](https://github.com/noetl/noetl/commit/cbcfb73e181b8bd652a599f28b7dd26f60ccf4cd))

## [2.3.1](https://github.com/noetl/noetl/compare/v2.3.0...v2.3.1) (2025-12-25)

### Bug Fixes

* fix errors, AHM-3901 ([93ee225](https://github.com/noetl/noetl/commit/93ee225cfa1529da2f332ad8fd6b70b2973d900c))
* remove useless and double logs, AHM-3901 ([13e0de1](https://github.com/noetl/noetl/commit/13e0de1134101ed62e493aa4f0bc739e68f34dae))

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
