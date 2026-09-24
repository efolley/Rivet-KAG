# Incident Response Runbook

Owner: Security team.

## Severity levels

SEV1 is a full outage or confirmed data breach. SEV2 is a major feature degraded or a suspected breach. SEV3 is a minor issue with a workaround. Target response times are 15 minutes for SEV1, 1 hour for SEV2 and next business day for SEV3.

## First steps

The on-call engineer acknowledges the alert, opens an incident channel named after the date and severity, and assigns an incident commander. Alerts come from Wazuh for security events and from Grafana for service health.

## Communication

The incident commander posts a status update every 30 minutes for SEV1 and every 2 hours for SEV2. The Product team owns customer communication. Security owns any regulator notification and must be involved in every suspected breach.

## After the incident

A blameless postmortem is written within 5 business days for SEV1 and SEV2 incidents. It lists the timeline, root cause, impact and follow-up actions with owners.
