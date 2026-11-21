# Wiring up real PagerDuty / Slack integrations

By default, `alertmanager/alertmanager.yml` routes alerts to a `page`
receiver (severity=critical) and a `ticket` receiver (severity=warning),
but neither one has an active integration - no webhook URL or API key is
committed to this repo, because that would be a leaked credential the
moment it's pushed to GitHub. Alerts still appear in the Alertmanager UI
and API (`http://localhost:9093`); they just aren't delivered anywhere
external. This is how to make that delivery real.

The pinned `prom/alertmanager` image (0.34.1) has no `${VAR}`-style
env-var expansion for secret fields - a field like `api_url:
'${SLACK_WEBHOOK_URL}'` is validated as a literal URL before any
expansion could happen, so it just fails to parse. Instead, each
integration points at a **file** Alertmanager reads at startup, via the
`routing_key_file` / `api_url_file` config fields. The file lives outside
version control; only its path is committed.

## PagerDuty (the `page` receiver)

1. In PagerDuty, create a service (or reuse one) and add an integration of
   type **Events API v2**. Copy its integration key.
2. Write it to a file under `alertmanager/secrets/` (this directory is
   gitignored - `git status` should show nothing after this step):

   ```bash
   mkdir -p alertmanager/secrets
   printf '%s' '<your-integration-key>' > alertmanager/secrets/pagerduty_routing_key
   ```

3. In `alertmanager/alertmanager.yml`, uncomment the `pagerduty_configs`
   block under the `page` receiver. It already points at
   `/etc/alertmanager/secrets/pagerduty_routing_key` - the same
   `./alertmanager:/etc/alertmanager:ro` volume mount `docker-compose.yml`
   already uses for `alertmanager.yml` itself also carries the
   `secrets/` subdirectory, so no compose changes are needed.
4. Validate the config and restart:

   ```bash
   make check
   docker compose up -d alertmanager
   ```

5. Confirm it: `make burn RATE=0.9` should produce a PagerDuty incident
   within the fast tier's `for: 2m` window (see
   [`docs/runbook.md`](runbook.md)).

## Slack (the `ticket` receiver)

1. In Slack, create (or reuse) an app with an **Incoming Webhook** pointed
   at the channel you want SLO tickets filed in. Copy the webhook URL.
2. Write it to a file under `alertmanager/secrets/`:

   ```bash
   mkdir -p alertmanager/secrets
   printf '%s' '<your-webhook-url>' > alertmanager/secrets/slack_webhook_url
   ```

3. In `alertmanager/alertmanager.yml`, uncomment the `slack_configs` block
   under the `ticket` receiver. It already points at
   `/etc/alertmanager/secrets/slack_webhook_url`.
4. `make check && docker compose up -d alertmanager`.

## Notes

- `printf '%s'` (not `echo`) avoids writing a trailing newline into the
  secret file - Alertmanager reads the file's contents verbatim as the
  routing key / URL, so a stray newline would end up as part of the
  value.
- `make check` (`amtool check-config`) validates the YAML and Go template
  syntax of both blocks without needing the secret files to exist or
  contain real credentials - safe to run any time, including with the
  integration blocks still commented out, or with the referenced files
  missing (`*_file` fields are only read when Alertmanager actually
  starts, not during `check-config`).
- Nothing under `alertmanager/secrets/` is ever committed - `.gitignore`
  excludes the whole directory except a placeholder `.gitkeep`, so
  `git status` after writing a secret file there should show nothing
  changed.
- The `inhibit_rules` in `alertmanager.yml` already prevent a single
  incident from paging *and* filing a ticket: once the fast tier fires,
  the slower tiers for the same `slo` label are inhibited. Wiring both
  integrations up is safe without worrying about duplicate noise.
