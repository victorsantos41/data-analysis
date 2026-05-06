# Project Context

## Objective

Pipeline de inteligência de mercado para energia solar.

## Current Architecture

RAW -> TRUSTED -> REFINED -> BUSINESS -> IBGE -> SOCIOECONOMIC -> SCORING

## Main Problem

TRUSTED -> REFINED está lenta devido ao reverse geocoding.

## Infrastructure

- AWS Lambda
- S3
- boto3
- Grafana
- JSON output

## Goal

Gerar ranking de regiões com maior potencial comercial para energia solar.

## Important Rules

- minimizar chamadas externas
- reduzir tamanho do JSON
- priorizar performance
- arquitetura serverless
- evitar processamento sequencial
