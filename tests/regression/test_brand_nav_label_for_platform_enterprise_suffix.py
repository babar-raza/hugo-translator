"""2026-09-10: "Aspose.X for <Platform> -- Enterprise <Suffix>" is a fixed
nav-label/CTA link (the portfolio's "See Also"/"Related Resources" footer
CTA), not prose -- but the brand-navigation-label check's "every word after
the brand token must be Title-Case" rule (deliberately added to keep real
sentences like "Aspose.3D FOSS for Java" translatable) also excluded this
shape, because of its lowercase "for" connector.

Two independent, portfolio-real failure modes traced to this exact gap:

- wave24 (blog.aspose.org/words/python): professionalize_llm mistranslated
  the "Enterprise Product" tail of "Aspose.Words for Python — Enterprise
  Product" into the target language (RB-006) in ar/hu/ja/ro, while other
  locales only got it right by model judgment, not producer guarantee.
- wave25 (docs.aspose.org/3d/net/developer-guide, 4 pages): BOTH
  professionalize_llm and m2m100_418m repeatedly hallucinated/duplicated
  "Aspose.3D for .NET — Enterprise Documentation" many times over in the
  same "## See Also" position, across ar/cs/de (LinkValidator
  source_count=2 vs translation_count=13) -- traced to this exact link via
  its n-gram hash in a live debug run, not assumed.

The fix must NOT relax the original narrow rule for real prose: "Aspose.3D
FOSS for Java" (the base rule's own worked example) and "Aspose.3D for .NET
is a great library" must stay translatable. The distinguishing signal is
the "-- Enterprise" (or em/en-dash) trigger immediately after the "for
<Platform>" clause -- present in every real CTA instance, absent from every
real sentence.
"""

import pytest

from src.translation_engine.extractor.text_unit_extractor import (
    _link_text_is_brand_navigation_label,
    _whole_node_is_brand_navigation_link,
)


@pytest.mark.parametrize(
    "anchor",
    [
        "Aspose.3D for .NET — Enterprise Documentation",  # wave25 (confirmed hallucination trigger)
        "Aspose.Words for Python — Enterprise Product",  # wave24 (confirmed RB-006 mistranslation)
        "Aspose.3D for TypeScript — Enterprise Blog",
        "Aspose.PDF for TypeScript — Enterprise Product Family",
        "Aspose.Words for .NET — Enterprise API Reference",
        "Aspose.3D for C++ — Enterprise Documentation",  # platform name with punctuation
        "Aspose.3D for Node.js — Enterprise Documentation",  # platform name with a dot
    ],
)
def test_for_platform_enterprise_suffix_is_a_protected_nav_label(anchor):
    assert _link_text_is_brand_navigation_label(anchor) is True


def test_wave25_see_also_link_is_protected_as_a_whole_list_item():
    markdown = "[Aspose.3D for .NET — Enterprise Documentation](https://docs.aspose.com/3d/net/)"
    assert _whole_node_is_brand_navigation_link(markdown) is True


@pytest.mark.parametrize(
    "anchor",
    [
        "Aspose.3D FOSS for Java",  # the base rule's own real-sentence example
        "Aspose.3D for .NET is a great library",  # real sentence, no Enterprise trigger
        "Aspose.3D for .NET",  # for-platform clause with nothing after it
        "Aspose.3D for .NET — enterprise documentation",  # lowercase trigger must not match
        "Aspose.3D for .NET does not use Enterprise features",  # Enterprise present but not as the tail
    ],
)
def test_real_prose_stays_translatable(anchor):
    assert _link_text_is_brand_navigation_label(anchor) is False
