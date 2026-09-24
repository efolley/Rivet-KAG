# Data Platform Handbook

Owner: Data Platform team, led by Priya Nair.

## Overview

The Data Platform team runs the company's data infrastructure. Its main project is Atlas, a migration from the legacy warehouse to a data lakehouse. Atlas started in January 2026 and is active.

## Architecture

Events are streamed through Kafka into the raw zone of the lakehouse. Airflow orchestrates batch transformations from raw to curated tables. The Beacon recommendation engine and the Compass dashboard both read from curated tables.

## Data quality

Every curated table has an owner, a freshness check and a row-count check. Failed checks page the on-call data engineer. Schema changes need a pull request reviewed by the table owner.

## Requesting access

Ask for access to a dataset with a ticket. The data owner approves it and the Security team grants it through Okta groups. Access to tables with personal data is limited to named individuals and reviewed every quarter.
