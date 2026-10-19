Usage
=====

As a command-line tool
----------------------

Pass a GitHub URL or ``owner/repo`` shorthand. Trailing slashes, a ``.git``
suffix and ``www.`` are tolerated:

.. code-block:: sh

   mibare BurntSushi/ripgrep
   mibare https://github.com/BurntSushi/ripgrep

The mise registry's backends for the repository are printed in registry order,
with the first marked as the recommendation. ``mibare`` needs a ``mise`` binary
(2026.10.13 or newer) on ``PATH`` and runs it in an isolated environment, so
your own mise settings never change the answer. ``GITHUB_TOKEN`` is passed
through when set.

Exit codes:

* ``0``: a recommendation was found.
* ``1``: no backend was found.
* ``2``: an error, such as input that is not a GitHub repository or a missing
  or too-old ``mise``.

As a library
------------

``resolve()`` returns the structured candidates that the command prints:

.. literalinclude:: examples/resolve_repository.py
   :language: python
   :caption: examples/resolve_repository.py
