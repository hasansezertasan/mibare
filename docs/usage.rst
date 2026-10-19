Usage
=====

As a library
------------

Look up the installed distribution version:

.. literalinclude:: examples/version_lookup.py
   :language: python
   :caption: examples/version_lookup.py

For short interactive snippets embedded in prose, the ``docs-doctest`` task
executes ``>>>`` blocks too:

.. doctest::

   >>> from mibare.__metadata__ import PROJECT_NAME
   >>> PROJECT_NAME
   'mibare'

As a command-line tool
----------------------

To use ``mibare`` as a command-line tool:

.. code-block:: sh

   mibare version
   mibare info

Or invoke it programmatically from Python:

.. literalinclude:: examples/cli_usage.py
   :language: python
   :caption: examples/cli_usage.py
