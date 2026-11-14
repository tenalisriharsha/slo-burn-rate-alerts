# Wiring up real PagerDuty / Slack integrations

By default, `alertmanager/alertmanager.yml` routes alerts to a `page`
receiver (severity=critical) and a `ticket` receiver (severity=warning),
but neither one has an active integration - no webhook URL or API key is
committed to this repo, because that would be a leaked credential the
moment it's pushed to GitHub. Alerts still appear in the Alertmanager UI
and API (`http://localhost:9093`); they just aren't delivered anywhere
external. This is how to make that delivery real.

## PagerDuty (the `page` receiver)

1. In PagerDuty, create a service (or reuse one) and add an integration of
   type **Events API v2**. Copy its integration key.
2. Export it as an environment variable before starting the stack:

   ```bash
   export PAGERDUTY_ROUTING_KEY=<your-integration-key>
   ```

3. In `docker-compose.yml`, add it to the `alertmanager` service's
   `environment:` block:

   ```yaml
   alertmanager:
     environment:
       PAGERDUTY_ROUTING_KEY: "${PAGERDUTY_ROUTING_KEY}"
   ```

4. In `alertmanager/alertmanager.yml`, uncomment the `pagerduty_configs`
   block under the `page` receiver.
5. Validate the config and restart:

   ```bash
   make check
   docker compose up -d alertmanager
   ```

6. Confirm it: `make burn RATE=0.9` should produce a PagerDuty incident
   within the fast tier's `for: 2m` window (see
   [`docs/runbook.md`](runbook.md)).

## Slack (the `ticket` receiver)

1. In Slack, create (or reuse) an app with an **Incoming Webhook** pointed
   at the channel you want SLO tickets filed in. Copy the webhook URL.
2. Export it:

   ```bash
   export SLACK_WEBHOOK_URL=<your-webhook-url>
   ```

3. Add it to the `alertmanager` service's `environment:` block in
   `docker-compose.yml`, the same way as `PAGERDUTY_ROUTING_KEY` above.
4. In `alertmanager/alertmanager.yml`, uncomment the `slack_configs` block
   under the `ticket` receiver.
5. `make check && docker compose up -d alertmanager`.

## Notes

- Alertmanager expands `${VAR}` references in its config file against its
  own process environment, so the secret itself never has to be written
  into `alertmanager.yml` - only the variable name is. Nothing in `git
  diff` after step 4 above should contain the real key or URL.
- `make check` (`amtool check-config`) validates the YAML and Go template
  syntax of both blocks without needing real credentials - safe to run any
  time, including with the integration blocks still commented out.
- The `inhibit_rules` in `alertmanager.yml` already prevent a single
  incident from paging *and* filing a ticket: once the fast tier fires,
  the slower tiers for the same `slo` label are inhibited. Wiring both
  integrations up is safe without worrying about duplicate noise.
