-- Add is_test column to executions table
-- Migration: 001_add_is_test_to_executions
-- Created: 2026-01-23

ALTER TABLE executions ADD COLUMN is_test BOOLEAN NOT NULL DEFAULT 0;
