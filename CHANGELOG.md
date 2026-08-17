# CHANGELOG

<!-- version list -->

## v2.0.0 (2026-08-17)

### Bug Fixes

- Harden session storage, token refresh, and request authentication
  ([`210b21f`](https://github.com/Techrocket9/grubhub-mcp/commit/210b21f43ce7e351e0aa8e7b7cfaeed8697ea2f8))

- Paginate order history server-side so the full history is reachable
  ([`4bd0ece`](https://github.com/Techrocket9/grubhub-mcp/commit/4bd0ece775b6376f034ea17693bcb51e0fa219f1))

- **deps**: Pin mcp to the 1.x line that still ships FastMCP
  ([`f7910c5`](https://github.com/Techrocket9/grubhub-mcp/commit/f7910c510dc0d3774ad57782db7ba29a218ace5d))

### Chores

- Keep the plugin manifest version in sync with the package
  ([`3a456c1`](https://github.com/Techrocket9/grubhub-mcp/commit/3a456c1ed60b436dcbe4f3ec4ffce71680178689))

### Continuous Integration

- Scope write permissions to the release job only
  ([`b792ec5`](https://github.com/Techrocket9/grubhub-mcp/commit/b792ec54c67d0b4a0ea403849b4bed0bcccf0991))

- Test on 3.11 and 3.12 before releasing, and tolerate forks
  ([`9320f03`](https://github.com/Techrocket9/grubhub-mcp/commit/9320f0351fcb9aa525dbdcbdaf4770f03b517c89))

### Documentation

- Document session storage, env-var login, and money-spending tools
  ([`055a9c5`](https://github.com/Techrocket9/grubhub-mcp/commit/055a9c5615ad5d47c6c56713f0701d99bdd77bdd))

- Document the confirmation gate and the tip cap
  ([`e160bd6`](https://github.com/Techrocket9/grubhub-mcp/commit/e160bd6bee759e190cf39474a15e34c6431b29ef))

- Point install instructions and plugin manifest at this fork
  ([`88f48dc`](https://github.com/Techrocket9/grubhub-mcp/commit/88f48dcf8ce4af2db71cd3a4dea437836d77b7af))

### Features

- Add safety annotations, structured errors, and input validation
  ([`193d2e4`](https://github.com/Techrocket9/grubhub-mcp/commit/193d2e478974a546bd0ed8ac3e97704b263597eb))

- Cap tip amounts at a configurable maximum
  ([`ae2ad31`](https://github.com/Techrocket9/grubhub-mcp/commit/ae2ad31d47a9edb83532a93634959f4c7414ee37))

- Require explicit confirmation before charging money
  ([`d692d1b`](https://github.com/Techrocket9/grubhub-mcp/commit/d692d1be66e43138bf52a80291168bf5536e17b0))

### Refactoring

- Stop sending Vary as a request header
  ([`d0f6abc`](https://github.com/Techrocket9/grubhub-mcp/commit/d0f6abc75a33412139201cbf18193597a67b854a))

### Testing

- Cover confirmation gating, the tip cap, and version sync
  ([`a2528f2`](https://github.com/Techrocket9/grubhub-mcp/commit/a2528f21a73898a0b69fe80ba8520d63949f8d2f))

- Cover session storage, auth recovery, pagination, and validation
  ([`156eb39`](https://github.com/Techrocket9/grubhub-mcp/commit/156eb390b360f76489faa2c2ee6efd5369769475))

### Breaking Changes

- Place_order and post_delivery_tip no longer charge anything unless called with confirm=true.


## v1.1.6 (2026-05-06)

### Bug Fixes

- Reconstruct reorder carts from order history
  ([`7c40515`](https://github.com/aserper/grubhub-mcp/commit/7c40515eab25f0fc057d472ab3815892526c37ca))


## v1.1.5 (2026-05-06)

### Bug Fixes

- Harden cart creation and auth error handling
  ([`876d946`](https://github.com/aserper/grubhub-mcp/commit/876d9466000c47257a30573cb8ff1faa799a0a52))


## v1.1.4 (2026-05-06)

### Bug Fixes

- Harden auth guards and order history fallbacks
  ([`4a8ca08`](https://github.com/aserper/grubhub-mcp/commit/4a8ca08303faac31708f7135318a513a3c3859e4))


## v1.1.3 (2026-03-24)

### Bug Fixes

- Fix search, autocomplete, profile, and payment endpoints
  ([`3f78fb2`](https://github.com/aserper/grubhub-mcp/commit/3f78fb2e7e4af6bcf6b41dd8b4dd7569badae63d))


## v1.1.2 (2026-03-24)

### Bug Fixes

- Correct API endpoint paths and diner_udid extraction
  ([`d523540`](https://github.com/aserper/grubhub-mcp/commit/d523540c00a0067bd9e34e7c43f6c65342f76c45))


## v1.1.1 (2026-03-24)

### Bug Fixes

- Add csrf_token to OTP verify flow and persist it across sessions
  ([`eb6f718`](https://github.com/aserper/grubhub-mcp/commit/eb6f718410261a23e2b79caa586b9656a73c6ab3))


## v1.1.0 (2026-03-24)

### Features

- Persist session to disk for stdio transports
  ([`44e14d1`](https://github.com/aserper/grubhub-mcp/commit/44e14d135a868b445d43da88961451f35a8dba58))


## v1.0.1 (2026-03-24)

### Bug Fixes

- Add build_command to semantic-release config
  ([`8843307`](https://github.com/aserper/grubhub-mcp/commit/88433073fd291c712c461d4e18e0960994892687))


## v1.0.0 (2026-03-24)

- Initial Release
