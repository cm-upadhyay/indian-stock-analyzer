# Changelog

## [0.5.1](https://github.com/cm-upadhyay/indian-stock-analyzer/compare/indian-stock-analyzer-v0.5.0...indian-stock-analyzer-v0.5.1) (2026-06-12)


### Bug Fixes

* API Lambda memory 1024MB ([896a6ec](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/896a6ecf25466d51bc2c98837a15303ea0f5caa8))
* API Lambda memory 1024MB ([b20490a](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/b20490a6eb8d8dbf7492a486f69dd9addce9783c))
* deploy.sh ([a8ecccc](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/a8ecccc5331536b518d01a4d0a5e3b77dbd203c6))
* deploy.sh no longer prints Lambda env secrets ([f368c5d](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/f368c5d6f18ba3e70a807da4d001cba28607fc96))
* lazy yfinance import — /accuracy cold start exceeded Lambda timeout ([203c137](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/203c13786befacc2e5447deb63c81924c78e03a6))
* lazy yfinance import in tracker ([9e32e02](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/9e32e021a3f5b782efbf5d4957553dec655bdc8d))
* lighthouse document-latency-insight as warn ([b165370](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/b165370c2a57efc7a0927ed47627bbd0acf70cac))
* lighthouse document-latency-insight as warn ([e6420a9](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/e6420a9dd2aae25a9c33873c9f2e63fe21a8491f))
* outcome tracker 5-day window, public accuracy endpoint ([b54eb97](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/b54eb9773697acf5ad78af2205ba76ed6e47317e))
* outcome tracker 5-day window, public accuracy endpoint ([7ba6b58](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/7ba6b58eeae841daff73b4213b9bed38e1de9407))
* precompute accuracy summary to stop /accuracy Lambda timeouts; dependabot grouping ([a655984](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/a6559849e19dece6c284f71614c970ffbc787daa))
* reviewer prompt truncation, analyst direction vote, 5-day target horizon ([7b03af3](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/7b03af3393e8e4d12b2c5b08722a37f56311a191))
* reviewer prompt truncation, wire analyst direction vote, 5-day target horizon ([6b8df7b](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/6b8df7b57af939cd49dec8e51b69b4d7dece3373))

## [0.5.0](https://github.com/cm-upadhyay/indian-stock-analyzer/compare/indian-stock-analyzer-v0.4.0...indian-stock-analyzer-v0.5.0) (2026-06-10)


### Features

* auth + Razorpay UI activation ([b4e1a47](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/b4e1a470525ce0c6d4c278e6983ddc532c9a7617))
* auth + Razorpay UI activation ([dcdc0fa](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/dcdc0face0e76b3b4af6462cbc7c33b1bd1ce7c2))
* CloudFront + WAF + API versioning ([#30](https://github.com/cm-upadhyay/indian-stock-analyzer/issues/30)) ([#31](https://github.com/cm-upadhyay/indian-stock-analyzer/issues/31)) ([6464c22](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/6464c22cb733ebd1475f829dfc3a1cc0e32709f7))
* minimal Next.js frontend on Vercel ([5f81217](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/5f812170928653588d41d76cbd7e241a0be1b4a7))
* minimal Next.js frontend on Vercel ([39aa106](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/39aa1066fca598efd9f2b9b6f5bf1caeda236fbe))
* Phase 2 backend — pipeline, API, indicators, LLM, tests ([1ca0361](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/1ca03611f4f4a3277ac8ad747ed444f847cd7a7c))
* Phase 2 backend — pipeline, API, indicators, LLM, tests ([b64ccda](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/b64ccda5f7aa037226e3f881f1d844a03bc16b91))
* Phase 3A — memory, MCP, reflection, guardrails, HITL, input security ([805879e](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/805879e8c2fa489a7c8d308b422db2733f3b21c9))
* Phase 3A — memory, MCP, reflection, guardrails, HITL, input security ([17fad81](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/17fad8131bed0df9fe76296ea087313853e1cced))
* Phase 3B+3C — ECS Fargate, observability, CI hardening, feature flags, semantic cache, SSE, JWT auth, frontend dashboard ([fb93260](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/fb9326000eb3dc24c969060e1f8bbea29e3f24b2))
* Phase 3B+3C — ECS Fargate, observability, CI hardening, feature… ([10b4e98](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/10b4e984a1c3ed072b1a5b860256b9758c28ee7a))
* Phase 4 CI/CD — CI layer 3, release automation, a11y ([#36](https://github.com/cm-upadhyay/indian-stock-analyzer/issues/36)) ([cea99c5](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/cea99c58889bc82a23502d8e5005ce87d5b132aa))
* Phase 4 infra-b — subscribers, HITL, IAM, CI deploy, alarms ([#33](https://github.com/cm-upadhyay/indian-stock-analyzer/issues/33)) ([830a62c](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/830a62c62c51e360276c51e50b57c770c1751123))
* wire email delivery, HTML reports, fix Telegram duplicates and SSM region ([91bc0be](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/91bc0be9df488c3102fc5a9be28324987df37f75))


### Bug Fixes

* CI ([#34](https://github.com/cm-upadhyay/indian-stock-analyzer/issues/34)) ([ee87fca](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/ee87fcaa1650d8e0f39e4f470f2617be5f2e35ba))
* Lambda-incompatiblity ([d0eb144](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/d0eb144b36829fc4a44a27bee02a42c9c665b4b8))
* Lambda-incompatiblity ([d581fb5](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/d581fb533b5030734e9b1954bd22584adcbb5132))
* lighthouse cls-culprits-insight ([#48](https://github.com/cm-upadhyay/indian-stock-analyzer/issues/48)) ([fae4d95](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/fae4d9504504322fe2eebbb0b9f469f40e4c0621))
* Security ([ceca47b](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/ceca47b4a2da96457f9795cb9a68d8d15bf58c12))
* security config ([db7fe24](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/db7fe244db3c716c74fbaa2ecb298900b6e82cdf))
* security config - semgrep and trivy ([5105f0d](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/5105f0ddb340125de8f0540a308253a40d2b7421))
* trivy config ([ca15221](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/ca152210d47766ed5850b5a00a78eff58156960a))
* UI ([9c4ea17](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/9c4ea175491c11c04440970d69fb667bcf3a8a6f))
* UI ([708e49c](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/708e49cb586b4c04a68aa03c721a474a431e7698))
* UI ([077277f](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/077277f8da56f6cfe623a9aa408a42240d253149))
* UI ([3b02732](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/3b0273220904b2ca395268f2883349d8e36d4b8c))
* UI ([97b22e7](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/97b22e77b0c10e93dffc1303cb97e9b539548ad4))
* UI ([777f4cf](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/777f4cff4820e955a6a2cca5fe54079d7d6a7da4))
* UX ([b902759](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/b90275929c8a03f1c02de314eb7f95ffdf20c0d8))
* UX ([f9639a0](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/f9639a03d33ca3d6ae8785dfe421d4ec1e17ec7d))


### CI / CD

* add workflow_dispatch to release-please; ignore eslint v10 in dependabot ([#38](https://github.com/cm-upadhyay/indian-stock-analyzer/issues/38)) ([796fb74](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/796fb74e15223916d57b0f154f09d93e9947e177))
* grant pull-requests read permission for gitleaks secret scan ([6d0e30f](https://github.com/cm-upadhyay/indian-stock-analyzer/commit/6d0e30ffe3e8be279be1c130ea2d39d9891c1f85))
