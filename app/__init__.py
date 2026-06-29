"""Automated research assistant — multi-agent literature review.

A Researcher Agent (Claude) plans searches and judges relevance; a Proxy Agent
executes calls to the Paperclip database (Semantic Scholar Graph API). Results
are filtered to high-impact journals, deduplicated by recency, summarized, and
saved to disk.
"""

__version__ = "0.1.0"
