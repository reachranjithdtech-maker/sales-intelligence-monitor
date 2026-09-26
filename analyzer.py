import json
import os
from database import get_prospect, add_signal, save_analysis, add_action_item

try:
    import anthropic
    HAS_ANTHROPIC = bool(os.environ.get("ANTHROPIC_API_KEY"))
except ImportError:
    HAS_ANTHROPIC = False

SIGNAL_TYPES = [
    "leadership_change",
    "technology_shift",
    "partnership_deal",
    "content_strategy",
    "market_expansion",
    "regulatory_change",
    "financial_event",
    "competitive_move",
    "ad_tech_shift",
    "platform_launch",
]

COMCAST_CAPABILITIES = """
Comcast Technology Solutions (CTS) provides:
- Video Distribution & Delivery: End-to-end managed video platform, transcoding, packaging,
  DRM, CDN, multi-screen delivery for OTT/linear/VOD
- Advertising Technology: FreeWheel ad management platform, programmatic advertising,
  server-side ad insertion (SSAI), dynamic ad insertion (DAI), addressable advertising
- Content Management: Metadata management, content workflow automation, rights management
- Analytics & Data: Audience measurement, content analytics, ad performance analytics
- Streaming Infrastructure: Cloud-native video platform, low-latency live streaming,
  scalable OTT architecture
- Ad Distribution: Linear and digital ad distribution across multiple platforms and geographies
- Monetization Solutions: AVOD, SVOD, TVOD, hybrid monetization models
"""

ANALYSIS_PROMPT = """You are a senior sales intelligence analyst at Comcast Technology Solutions (CTS).
Your job is to analyze business signals about target customers and prospects in the
OTT/Video/Broadcasting/Advertising technology space and convert them into actionable
sales intelligence.

Here are Comcast's key capabilities:
{capabilities}

Given the following signal about a prospect, provide a structured analysis following
the exact flow: Signal → Context → Business Implication → Comcast Opportunity → Recommended Action.

PROSPECT: {prospect_name}
INDUSTRY/SEGMENT: {segment}
REGION: {region}

SIGNAL TYPE: {signal_type}
SIGNAL: {signal_headline}
SIGNAL DETAILS: {signal_summary}

Provide your analysis as a JSON object with these exact fields:
{{
    "context": "2-3 sentences explaining the broader context of this signal - what's happening in the market, why this company is making this move, what trends this reflects",
    "business_implication": "2-3 sentences on what this means for the prospect's business - how it affects their operations, revenue, competitive position, or technology needs",
    "comcast_opportunity": "2-3 sentences on the specific Comcast Technology Solutions opportunity - which CTS products/services align with this need, potential deal size category (small/medium/large/strategic), and why CTS is uniquely positioned",
    "recommended_action": "3-5 specific, actionable next steps for the account team, numbered. Include who should do what, by when, and what to prepare",
    "urgency": "high, medium, or low - based on time sensitivity and competitive pressure",
    "confidence_score": 0.0 to 1.0 - how confident you are in this analysis,
    "opportunity_value": "estimated deal category: small (<$100K), medium ($100K-$500K), large ($500K-$2M), strategic (>$2M)"
}}

Be specific to Comcast's actual capabilities. Reference real products like FreeWheel where relevant.
Consider the prospect's region and segment when making recommendations.
Return ONLY the JSON object, no additional text.
"""


def analyze_signal_with_ai(signal_id, prospect_id, signal_type, headline, summary):
    prospect = get_prospect(prospect_id)
    if not prospect:
        return None

    if not HAS_ANTHROPIC:
        return _generate_rule_based_analysis(
            prospect, signal_type, headline, summary, signal_id=signal_id
        )

    client = anthropic.Anthropic()

    prompt = ANALYSIS_PROMPT.format(
        capabilities=COMCAST_CAPABILITIES,
        prospect_name=prospect["account_name"],
        segment=prospect.get("segment", "unknown"),
        region=prospect.get("region", "unknown"),
        signal_type=signal_type,
        signal_headline=headline,
        signal_summary=summary or headline,
    )

    try:
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=2000,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text = block.text
                break

        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            if response_text.endswith("```"):
                response_text = response_text[:-3]

        analysis = json.loads(response_text)

        analysis_id = save_analysis(
            signal_id=signal_id,
            prospect_id=prospect_id,
            context=analysis["context"],
            business_implication=analysis["business_implication"],
            comcast_opportunity=analysis["comcast_opportunity"],
            recommended_action=analysis["recommended_action"],
            urgency=analysis.get("urgency", "medium"),
            confidence_score=analysis.get("confidence_score", 0.5),
            opportunity_value=analysis.get("opportunity_value", "medium"),
        )

        actions = analysis["recommended_action"].split("\n")
        for action in actions:
            action = action.strip()
            if action and (action[0].isdigit() or action.startswith("-")):
                action_text = action.lstrip("0123456789.-) ").strip()
                if action_text:
                    add_action_item(
                        analysis_id=analysis_id,
                        prospect_id=prospect_id,
                        action_text=action_text,
                        action_type=signal_type,
                    )

        return analysis_id

    except Exception as e:
        print(f"AI analysis failed: {e}")
        return _generate_rule_based_analysis(
            prospect, signal_type, headline, summary, signal_id=signal_id
        )


RULE_BASED_TEMPLATES = {
    "leadership_change": {
        "context": "Leadership changes at {name} signal a potential strategic shift. New executives often reassess technology partnerships and vendor relationships within their first 90 days, creating a window for engagement.",
        "business_implication": "The new leadership may re-evaluate existing technology stack and vendor contracts. This creates both risk (if we're an incumbent) and opportunity (if we're looking to enter) for the {segment} segment in {region}.",
        "comcast_opportunity": "CTS can position its end-to-end video platform and FreeWheel ad technology as the modern, unified solution the new leadership wants. This is a medium-to-large opportunity depending on current infrastructure.",
        "recommended_action": "1. Research the new executive's background and technology preferences\n2. Prepare a tailored CTS capabilities deck focused on {segment}\n3. Request an introductory meeting within 30 days\n4. Identify mutual connections for a warm introduction",
        "urgency": "high",
        "confidence": 0.7,
        "value": "medium ($100K-$500K)",
    },
    "technology_shift": {
        "context": "{name} is undergoing a technology transformation, reflecting the broader industry trend of migrating to cloud-native, scalable video infrastructure in the {region} market.",
        "business_implication": "This technology shift requires new infrastructure, expertise, and partnerships. {name} will need reliable technology partners who can deliver at scale and reduce time-to-market for their {segment} operations.",
        "comcast_opportunity": "CTS's cloud-native video platform, transcoding/packaging pipeline, and CDN solutions directly address the needs of this migration. FreeWheel's ad management can modernize their monetization stack simultaneously.",
        "recommended_action": "1. Prepare a technology migration roadmap showing CTS platform capabilities\n2. Arrange a technical deep-dive with their engineering team\n3. Propose a proof-of-concept for a specific workflow\n4. Share relevant case studies from similar {segment} deployments",
        "urgency": "high",
        "confidence": 0.8,
        "value": "large ($500K-$2M)",
    },
    "partnership_deal": {
        "context": "{name} is forming strategic partnerships to strengthen their position in the {region} {segment} market. Partnership announcements often signal expansion plans and increased infrastructure needs.",
        "business_implication": "New partnerships typically increase content volume, audience reach, and advertising inventory — all of which require scalable technology infrastructure and monetization solutions.",
        "comcast_opportunity": "CTS can serve as the technology backbone enabling these partnerships — from content distribution and multi-platform delivery to unified ad management across partner properties via FreeWheel.",
        "recommended_action": "1. Map the partnership implications for technology requirements\n2. Position CTS as the neutral technology enabler for both parties\n3. Propose a joint meeting with both partners to discuss shared infrastructure\n4. Prepare an ROI analysis showing cost savings from unified platform approach",
        "urgency": "medium",
        "confidence": 0.7,
        "value": "large ($500K-$2M)",
    },
    "content_strategy": {
        "context": "{name} is evolving its content strategy, reflecting competitive dynamics in the {region} {segment} space where content differentiation and distribution quality are key battlegrounds.",
        "business_implication": "New content strategies require robust content management, multi-format delivery, rights management, and potentially new monetization models (AVOD/SVOD/hybrid).",
        "comcast_opportunity": "CTS content management and workflow automation tools can streamline content operations. FreeWheel enables flexible monetization across AVOD, SVOD, and hybrid models.",
        "recommended_action": "1. Analyze their content pipeline and distribution challenges\n2. Demonstrate CTS content workflow automation capabilities\n3. Present FreeWheel's flexible monetization options\n4. Propose a content operations assessment",
        "urgency": "medium",
        "confidence": 0.6,
        "value": "medium ($100K-$500K)",
    },
    "market_expansion": {
        "context": "{name} is expanding into new markets or geographies from their {region} base. Market expansion in the {segment} space demands scalable infrastructure that can handle multi-region, multi-language content delivery.",
        "business_implication": "Geographic expansion multiplies technology complexity — multi-CDN orchestration, regional compliance, localized ad insertion, and audience measurement across markets become critical requirements.",
        "comcast_opportunity": "CTS's global video delivery infrastructure and FreeWheel's multi-market ad management are purpose-built for cross-border expansion. This is a strategic opportunity given the scale of infrastructure needed.",
        "recommended_action": "1. Map their expansion targets and identify technology gaps\n2. Present CTS's multi-region delivery architecture\n3. Highlight FreeWheel's programmatic capabilities in target markets\n4. Propose a phased deployment plan starting with the first expansion market\n5. Connect them with CTS's regional technical teams",
        "urgency": "high",
        "confidence": 0.75,
        "value": "strategic (>$2M)",
    },
    "ad_tech_shift": {
        "context": "{name} is rethinking its advertising technology strategy, part of a broader {region} market shift toward programmatic, addressable, and data-driven advertising in the {segment} space.",
        "business_implication": "Ad tech modernization directly impacts revenue streams. Moving to programmatic and addressable capabilities can increase ad yield by 20-40% but requires significant platform investment.",
        "comcast_opportunity": "FreeWheel is the industry-leading ad management platform for premium video. CTS can offer server-side ad insertion (SSAI), dynamic ad insertion (DAI), and comprehensive ad analytics — exactly what this shift demands.",
        "recommended_action": "1. Schedule a FreeWheel demo focused on their specific ad tech needs\n2. Prepare a competitive analysis vs. their current ad stack\n3. Build an ROI model showing ad yield improvement potential\n4. Propose a pilot with a subset of their inventory",
        "urgency": "high",
        "confidence": 0.85,
        "value": "large ($500K-$2M)",
    },
}

DEFAULT_TEMPLATE = {
    "context": "{name} shows notable activity in the {region} {segment} market that could indicate changing technology needs or strategic priorities.",
    "business_implication": "This development may create new requirements for video technology, content management, or advertising solutions as {name} adapts to market changes.",
    "comcast_opportunity": "CTS can position its comprehensive video platform and FreeWheel ad technology to address emerging needs. Initial engagement should focus on understanding their specific requirements.",
    "recommended_action": "1. Research the full context of this development\n2. Identify the right stakeholders at {name}\n3. Prepare a relevant CTS capabilities overview\n4. Request a discovery meeting to understand their needs",
    "urgency": "medium",
    "confidence": 0.5,
    "value": "medium ($100K-$500K)",
}


def _generate_rule_based_analysis(prospect, signal_type, headline, summary,
                                  signal_id=None):
    template = RULE_BASED_TEMPLATES.get(signal_type, DEFAULT_TEMPLATE)
    name = prospect["account_name"]
    region = prospect.get("region", "APAC")
    segment = prospect.get("segment", "media")

    fmt = {"name": name, "region": region, "segment": segment}

    analysis_id = save_analysis(
        signal_id=signal_id,
        prospect_id=prospect["id"],
        context=template["context"].format(**fmt),
        business_implication=template["business_implication"].format(**fmt),
        comcast_opportunity=template["comcast_opportunity"].format(**fmt),
        recommended_action=template["recommended_action"].format(**fmt),
        urgency=template["urgency"],
        confidence_score=template["confidence"],
        opportunity_value=template["value"],
    )

    actions = template["recommended_action"].format(**fmt).split("\n")
    for action in actions:
        action = action.strip()
        if action and action[0].isdigit():
            action_text = action.lstrip("0123456789.-) ").strip()
            if action_text:
                add_action_item(
                    analysis_id=analysis_id,
                    prospect_id=prospect["id"],
                    action_text=action_text,
                    action_type=signal_type,
                )

    return analysis_id


def generate_sample_signals(prospect_id):
    """Generate realistic sample signals for a prospect for demo purposes."""
    prospect = get_prospect(prospect_id)
    if not prospect:
        return []

    name = prospect["account_name"]
    region = prospect.get("region", "apac")
    segment = prospect.get("segment", "broadcaster")

    samples = []

    if "ott" in segment or "platform" in segment:
        samples.extend([
            ("technology_shift", f"{name} announces migration to cloud-native streaming infrastructure",
             f"{name} revealed plans to migrate its streaming platform to a cloud-native architecture, aiming to reduce latency and improve scalability for its growing subscriber base."),
            ("ad_tech_shift", f"{name} seeking programmatic advertising partners for AVOD expansion",
             f"{name} is actively evaluating server-side ad insertion (SSAI) solutions as it expands its ad-supported content tier across multiple markets."),
            ("content_strategy", f"{name} invests in original content production, plans 200+ hours of new programming",
             f"{name} announced a major content investment, requiring enhanced content management workflows and multi-platform distribution capabilities."),
        ])
    elif "telecom" in segment:
        samples.extend([
            ("platform_launch", f"{name} launching integrated OTT platform bundled with connectivity",
             f"{name} plans to launch a bundled OTT streaming service for its mobile and broadband subscribers, requiring end-to-end video platform infrastructure."),
            ("market_expansion", f"{name} expanding video services across Southeast Asian markets",
             f"{name} is rolling out its video platform to additional markets in the region, requiring multi-CDN orchestration and localized content delivery."),
            ("partnership_deal", f"{name} partners with global content providers for premium streaming",
             f"{name} signed content licensing agreements with major studios, increasing its need for DRM, rights management, and content workflow automation."),
        ])
    else:
        samples.extend([
            ("leadership_change", f"New CTO appointed at {name} with digital-first mandate",
             f"{name} appointed a new Chief Technology Officer with a background in streaming technology, signaling a push toward digital transformation of their broadcast operations."),
            ("technology_shift", f"{name} RFP for cloud video platform to replace legacy infrastructure",
             f"{name} has issued an RFP for a cloud-based video management and distribution platform to modernize their aging on-premises broadcast infrastructure."),
            ("ad_tech_shift", f"{name} exploring addressable TV advertising capabilities",
             f"{name} is evaluating addressable advertising solutions to increase ad revenue per viewer and offer more targeted advertising across their linear and digital properties."),
        ])

    signal_ids = []
    for signal_type, headline, summary in samples:
        severity = "high" if signal_type in ("technology_shift", "platform_launch") else "medium"
        sid = add_signal(prospect_id, signal_type, headline, summary,
                         source="Industry Intelligence", severity=severity)
        signal_ids.append(sid)

    return signal_ids
