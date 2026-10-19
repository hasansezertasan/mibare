.. A 7-character "=" underline (the length of "Modules") is treated as a
   merge-conflict separator by ``git diff --check`` / ``check-merge-conflict``;
   keep this underline longer than the title to avoid the false positive.

Modules
=========

An overview of the packages that make up ``mibare``.
The API reference below is generated automatically from the source docstrings.

Core (``mibare.core``)
------------------------------

Always-included infrastructure.

.. automodule:: mibare.core.resolve

.. automodule:: mibare.core.repository

.. automodule:: mibare.core.mise

.. automodule:: mibare.core.errors

.. automodule:: mibare.core.config

.. automodule:: mibare.core.dirs

.. automodule:: mibare.core.logging_setup

Utilities (``mibare.utils``)
------------------------------

Shared helper functions.

.. automodule:: mibare.utils

CLI (``mibare.cli``)
------------------------------

Thin Typer command-line wrapper around the library core.

.. automodule:: mibare.cli.app
