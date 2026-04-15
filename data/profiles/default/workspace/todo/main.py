#!/usr/bin/env python3
"""Simple command-line TODO app."""

import argparse
import json
import sys
from pathlib import Path

TASKS_FILE = Path(__file__).parent / "tasks.json"


def load_tasks() -> list[dict]:
    """Load tasks from tasks.json, returning an empty list if it doesn't exist."""
    if TASKS_FILE.exists():
        with TASKS_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_tasks(tasks: list[dict]) -> None:
    """Persist tasks to tasks.json."""
    with TASKS_FILE.open("w", encoding="utf-8") as f:
        json.dump(tasks, f, indent=2)


def next_id(tasks: list[dict]) -> int:
    """Return the next available integer ID."""
    return max((t["id"] for t in tasks), default=0) + 1


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_add(args: argparse.Namespace) -> None:
    """Add a new task."""
    tasks = load_tasks()
    task = {"id": next_id(tasks), "title": args.title, "done": False}
    tasks.append(task)
    save_tasks(tasks)
    print(f"Added task #{task['id']}: {task['title']}")


def cmd_list(args: argparse.Namespace) -> None:  # noqa: ARG001
    """List all tasks."""
    tasks = load_tasks()
    if not tasks:
        print("No tasks yet. Use 'add' to create one.")
        return
    for task in tasks:
        status = "x" if task["done"] else " "
        print(f"  [{status}] #{task['id']} {task['title']}")


def cmd_done(args: argparse.Namespace) -> None:
    """Mark a task as done."""
    tasks = load_tasks()
    for task in tasks:
        if task["id"] == args.id:
            if task["done"]:
                print(f"Task #{args.id} is already marked done.")
            else:
                task["done"] = True
                save_tasks(tasks)
                print(f"Marked task #{args.id} as done: {task['title']}")
            return
    print(f"Error: no task with id {args.id}.", file=sys.stderr)
    sys.exit(1)


def cmd_remove(args: argparse.Namespace) -> None:
    """Remove a task by ID."""
    tasks = load_tasks()
    remaining = [t for t in tasks if t["id"] != args.id]
    if len(remaining) == len(tasks):
        print(f"Error: no task with id {args.id}.", file=sys.stderr)
        sys.exit(1)
    save_tasks(remaining)
    print(f"Removed task #{args.id}.")


# ---------------------------------------------------------------------------
# CLI wiring
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="todo",
        description="A simple command-line TODO manager.",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # add
    p_add = sub.add_parser("add", help="Add a new task")
    p_add.add_argument("title", help="Task description")
    p_add.set_defaults(func=cmd_add)

    # list
    p_list = sub.add_parser("list", help="List all tasks")
    p_list.set_defaults(func=cmd_list)

    # done
    p_done = sub.add_parser("done", help="Mark a task as done")
    p_done.add_argument("id", type=int, help="Task ID")
    p_done.set_defaults(func=cmd_done)

    # remove
    p_remove = sub.add_parser("remove", help="Remove a task")
    p_remove.add_argument("id", type=int, help="Task ID")
    p_remove.set_defaults(func=cmd_remove)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
