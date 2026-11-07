"""Local playbook for music, video, and this product.

Adapted from a few ideas in Corey Haines' marketingskills, not a copy of
that repository and not a runtime dependency:

https://github.com/coreyhaines31/marketingskills

MIT License

Copyright (c) 2025 Corey Haines

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Ideas kept, and narrowed so this package does not execute those skills:

- product-marketing: write the audience, the alternative, and the message
  before treating them as settled. Without proof they stay hypotheses.
- customer-research: a job to be done and the listener's own words are
  research questions. Audio features do not answer them. This package does
  not mine the web.
- analytics: a rate is a numerator over a denominator for the same dated
  window. A missing value stays null. Do not fill gaps.
- ab-testing: start from a hypothesis and change one thing. Two dated rows
  can describe a change. They are not statistical significance.
- video: state the platform, the length, and one opening as a hypothesis.
  This command does not render, publish, or call a video model.

Music uses the same shape: one audience hypothesis, one message hypothesis,
and no claim that a song will chart.
"""

from __future__ import annotations

ATTRIBUTION = {
    "source": "https://github.com/coreyhaines31/marketingskills",
    "author": "Corey Haines",
    "license": "MIT",
    "copyright": "Copyright (c) 2025 Corey Haines",
    "adapted_from": [
        "skills/product-marketing",
        "skills/customer-research",
        "skills/analytics",
        "skills/ab-testing",
        "skills/video",
    ],
    "not_vendored": True,
    "skills_executed": False,
}

CHECKLIST = [
    "Write the audience and one message as hypotheses. A brief is not listener research.",
    "For a video, name the platform, the length, and one opening. Do not render or publish it here.",
    "Import a Trends CSV and a first-party analytics CSV you already downloaded. Do not connect an account.",
    "Compare tests only after two dated observations of the same metric each have a denominator.",
    "Record ratings, corrections, and campaign outcomes in the feedback file. That is not model training.",
    "Leave the master unrendered. Target -14 LUFS, no fade-out, cuts on the beat and never mid-word, and ask Travis before any master.",
]


def hypotheses_for_asset(*, goal: str, audience: str, campaign: str) -> list[dict]:
    """Audience and message hypotheses for one unmastered brief. Not findings."""
    audience_text = audience.strip()
    campaign_text = campaign.strip()
    if audience_text:
        audience_line = (
            f"The audience to write down is the one in the notes: {audience_text}. "
            "This is a hypothesis until listeners say it in their own words."
        )
    else:
        audience_line = (
            f"For a {goal} goal, write who the record is for before testing a message. "
            "Audio features do not name an audience. This is a hypothesis, not a finding."
        )
    if campaign_text:
        message_line = (
            f"The message to test is the campaign line you supplied: {campaign_text}. "
            "Test that line against one alternative. This is a hypothesis."
        )
    else:
        message_line = (
            "No campaign line was supplied. Write one message and one alternative. "
            "This is a hypothesis, not a strategy."
        )
    return [
        {
            "label": "hypothesis",
            "lane": "audience",
            "surface": "music",
            "text": audience_line,
            "proof": None,
            "not_a_finding": True,
        },
        {
            "label": "hypothesis",
            "lane": "message",
            "surface": "music",
            "text": message_line,
            "proof": None,
            "not_a_finding": True,
        },
        {
            "label": "hypothesis",
            "lane": "video",
            "surface": "video",
            "text": (
                "A video test names one platform, one length, and one opening against one alternative. "
                "Score it later with view-through over impressions from an export you downloaded. "
                "This is a hypothesis. This command does not render or publish a video."
            ),
            "proof": None,
            "not_a_finding": True,
        },
        {
            "label": "hypothesis",
            "lane": "product",
            "surface": "open_ar",
            "text": (
                "The job for this product is a local brief that keeps similarity, listener ratings, "
                "and attention in separate lanes. Positioning stays a hypothesis until you correct it "
                "with notes you supply. This is not a claim about who will stream the song."
            ),
            "proof": None,
            "not_a_finding": True,
        },
    ]
