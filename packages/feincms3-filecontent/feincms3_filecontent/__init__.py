"""
feincms3-filecontent: editorial content stored as flat files, versioned by Git,
structured and served by feincms3.

Layers (outermost to innermost)::

    Remote Git repository  -> persistent, versioned authority
    GitRepository          -> clone/fetch/pull/push/status/diff/log
    Local working tree     -> operational copy
    ContentStore           -> safe filesystem reads and writes
    Document               -> normalized file (front matter + body)
    ContentIndex           -> rebuildable ORM projection
    FileContent plugin     -> feincms3 integration

Git never participates in the HTTP hot path: rendering only touches the
ContentStore (the local filesystem).
"""

__version__ = "0.1.0"
