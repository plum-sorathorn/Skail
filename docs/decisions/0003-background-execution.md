# ADR 0003: Keep background execution experimental

Status: Accepted
Date: 2026-09-02
Depends on: [ADR 0002](./0002-framework-version-contract.md)

## Context

DeepAgents' synchronous subagents provide the stable foreground task path, including concurrent
task calls while the lead waits for their results. Its asynchronous subagent API adds individual
status, steering, and cancellation but remains preview functionality with different lifecycle and
deployment assumptions.

## Decision

The stable Rudder release uses `ForegroundTaskExecutor`. `BackgroundTaskExecutor` remains an
explicit experimental adapter boundary and is disabled by default. Stable callers depend only on
the Rudder `TaskExecutor` protocol. Background unavailability is a structured error and cannot
change foreground behavior.

Whole-run cancellation is supported for foreground work. User-facing individual steering and
cancellation appear only when an enabled executor reports that capability. No server, daemon, or
Agent Protocol dependency is introduced into the stable path.

## Consequences

Background work is not a stable-release blocker. It may be completed as post-stable Task P.2 after
its preview lifecycle, checkpoint, update, and cancellation contracts pass without weakening the
global scheduler, budgets, task attempts, or shared-workspace write lease.
