"""flowpath's own site content, ported from the flowpath repo (src/data.ts).

This is the Lead Handler's only source of facts. To change what the agent
knows, change it here (or in flowpath first, then copy it across), and the
passages rebuild on the next start.
"""
SITE = {
    "name": "flowpath",
    "email": "hello@flowpath.example",
    "phone": "+92 300 0000000",
    "address": "Gulberg III, Lahore",
}

SERVICES = [
    {
        "id": "social-media",
        "name": "Social media",
        "long": "Most brand pages post when someone remembers to. We run yours on a monthly plan agreed with you in "
                "advance, shoot and edit the content ourselves, and reply to comments and messages within working hours "
                "so nobody is left waiting.",
        "items": ["Monthly content calendar", "Reels and short video", "Community management"],
        "monthly": ["12 to 20 posts across your platforms", "4 to 8 short videos", "Replies to comments and messages",
                    "A one-page report on reach and saves"],
    },
    {
        "id": "paid-advertising",
        "name": "Paid advertising",
        "long": "We start from two numbers: what you can afford to pay for a customer, and what that customer spends over "
                "a year. Every campaign is judged against those, and we switch off what does not earn its budget, "
                "including ads we liked.",
        "items": ["Meta and TikTok ads", "Google Search and Shopping", "Weekly budget reviews"],
        "monthly": ["Campaign builds and creative tests", "Weekly budget and bid reviews",
                    "New ad creative every two weeks", "A report of spend against orders"],
    },
    {
        "id": "seo",
        "name": "Search and SEO",
        "long": "Search work is slow and it compounds. In the first month we fix the technical problems that hold your "
                "site back. After that we publish pages that answer the exact questions your customers type, and we "
                "track where each one ranks.",
        "items": ["Technical site audit", "Keyword and content plan", "Local search listings"],
        "monthly": ["A technical fix list, done for you", "4 new or rewritten pages", "Google Business profile updates",
                    "Rankings tracked for your key searches"],
    },
]

CASES = [
    {
        "slug": "koel-skincare", "client": "Koel Skincare", "sector": "Skincare, online store",
        "duration": "Six months", "services": ["Paid advertising", "Social media", "Store rebuild"],
        "did": "Store rebuild, paid social and creator videos", "result": "Revenue up 5.3 times in six months",
        "brief": "Koel was selling almost entirely through Instagram messages. Orders were limited by how fast two people "
                 "could reply, and nobody knew which posts actually led to sales.",
        "approach": [
            "Rebuilt the online store so customers could order without sending a message.",
            "Filmed twelve short videos with three creators who already used the products.",
            "Ran paid campaigns on Meta and TikTok, and stopped every ad that cost more than its orders were worth.",
            "Added a welcome email and a reorder reminder at 45 days.",
        ],
        "metrics": ["5.3x Monthly revenue, month six against month one", "41% Lower cost for each new order",
                    "212k New followers across three platforms"],
    },
    {
        "slug": "tandoor-street", "client": "Tandoor Street", "sector": "Restaurant, DHA Lahore",
        "duration": "Eight weeks", "services": ["Social media", "Paid advertising"],
        "did": "Launch campaign for a new restaurant in DHA", "result": "Fully booked for the first three weekends",
        "brief": "A new restaurant with no following, opening in a neighbourhood that already had forty places to eat. "
                 "The owners needed full tables from the first weekend, not the third month.",
        "approach": [
            "Filmed the kitchen for two weeks before opening and posted one short video a day.",
            "Invited sixty local food writers and creators to two preview nights.",
            "Ran ads only within eight kilometres of the restaurant, with a reservation link.",
            "Set up Google Business with the menu, photos and booking so searches led straight to a table.",
        ],
        "metrics": ["3 Fully booked weekends from opening day", "1.4m Video views in the launch month",
                    "62% Of reservations made through the ad link"],
    },
    {
        "slug": "sabz-homes", "client": "Sabz Homes", "sector": "Housing developer",
        "duration": "Five months", "services": ["Search and SEO", "Paid advertising"],
        "did": "Search ads and landing pages for a housing project",
        "result": "Cost for each enquiry cut by more than half",
        "brief": "Sabz Homes was paying for clicks from people who were browsing, not buying. The sales team spent most "
                 "of its day calling enquiries that went nowhere.",
        "approach": [
            "Rewrote the search campaigns around the words serious buyers use, such as plot sizes and payment plans.",
            "Built a separate landing page for each plot size, with the price and plan shown up front.",
            "Added three questions to the enquiry form so the sales team could call the strongest leads first.",
            "Published guides on payment plans and possession dates that now rank on the first page.",
        ],
        "metrics": ["54% Lower cost for each enquiry", "2.1x More site visits booked each month",
                    "9 Searches where the site ranks on page one"],
    },
    {
        "slug": "rangrez-studio", "client": "Rangrez Studio", "sector": "Clothing label",
        "duration": "Six weeks", "services": ["Social media", "Email and WhatsApp"],
        "did": "Eid collection film and email flows", "result": "Sold out in nine days",
        "brief": "Rangrez releases one large collection before each Eid. The previous launch sold slowly and ended in a "
                 "discount, which the founder did not want to repeat.",
        "approach": [
            "Made a ninety-second film of the collection and cut it into fourteen shorter pieces.",
            "Opened a waiting list three weeks early and gave it first access for 24 hours.",
            "Sent past customers a WhatsApp preview with their usual size already selected.",
            "Held back paid ads until day three, then pointed them only at what was still in stock.",
        ],
        "metrics": ["9 Days to sell out the collection", "34% Of orders from returning customers",
                    "0 Pieces sold at a discount"],
    },
]

STEPS = [
    ("Audit", "Two weeks inside your numbers, your pages and your competitors, ending in a written report you keep."),
    ("Plan", "One page that says who we are talking to, what we will say, where, and what it should cost."),
    ("Launch", "We make the content, build the campaigns and switch them on, with small tests before big budgets."),
    ("Report", "A plain-language report every month: what we spent, what came back and what we change next."),
]

FACTS = [
    ("Since", "2019"),
    ("Based in", "Lahore, working worldwide"),
    ("Team", "14 strategists, makers and media buyers"),
    ("Clients", "Retail, food, property and fashion"),
]

VALUES = [
    ("We show the numbers", "You get access to the ad accounts and the analytics. Nothing is reported that you cannot "
                            "check yourself."),
    ("We switch things off", "If an ad, a channel or a whole idea is not paying for itself, we say so and stop it."),
    ("One team, one plan", "The people who plan your campaign are the people who make it and report on it."),
]

ROLES = [
    ("Media buyer", "Full time, Lahore", "Two or more years running Meta and Google campaigns with real budgets."),
    ("Video editor", "Full time, Lahore or remote", "Short-form editing for Reels and TikTok, with motion graphics a plus."),
]

FAQS = [
    ("How much does it cost?", "Most clients spend between Rs 150,000 and Rs 400,000 a month with us, plus their ad "
                               "budget. We quote a fixed monthly fee after the audit, so there are no surprises."),
    ("Is there a minimum contract?", "Three months, because that is how long it takes to see what works. After that it "
                                     "runs month to month."),
    ("Who owns the ad accounts and content?", "You do. Everything is set up in your name, and you keep it if we stop "
                                              "working together."),
    ("How soon will we see results?", "Paid campaigns usually show a clear direction within four to six weeks. Search "
                                      "and SEO take three to six months."),
    ("Do you work with small businesses?", "Yes. About half our clients have fewer than twenty staff. We scope the work "
                                           "to the budget you have."),
]

# flowpath's contact form uses these bands, so leads are scored on the studio's own scale
BUDGET_BANDS = [
    ("under_150k", "Under Rs 150,000 a month", 0, 150_000),
    ("150k_400k", "Rs 150,000 to 400,000 a month", 150_000, 400_000),
    ("400k_1m", "Rs 400,000 to 1,000,000 a month", 400_000, 1_000_000),
    ("over_1m", "More than Rs 1,000,000 a month", 1_000_000, None),
]

SERVICE_IDS = [s["id"] for s in SERVICES]


def build_passages() -> list[dict]:
    """Cut the content into small passages, the same way flowpath's assistant does."""
    passages = []
    for s in SERVICES:
        passages.append({
            "id": f"service-{s['id']}", "title": f"Service: {s['name']}", "label": s["name"],
            "url": f"/services#{s['id']}",
            "text": f"{s['long']} What you get each month: {'; '.join(s['monthly'])}. "
                    f"Includes: {', '.join(s['items'])}.",
        })
    passages.append({
        "id": "services-overview", "title": "Services we offer", "label": "Our services", "url": "/services",
        "text": f"flowpath offers three services: {', '.join(s['name'] for s in SERVICES)}. Clients can take one or "
                "all three, with one team, one plan and one report.",
    })
    for c in CASES:
        passages.append({
            "id": f"case-{c['slug']}", "title": f"Case study: {c['client']} ({c['sector']})",
            "label": f"{c['client']} case study", "url": f"/work/{c['slug']}",
            "text": f"{c['did']}. Result: {c['result']}. The brief: {c['brief']} What we did: {' '.join(c['approach'])} "
                    f"Numbers: {'; '.join(c['metrics'])}. Length: {c['duration']}. "
                    f"Services used: {', '.join(c['services'])}.",
        })
    for i, (question, answer) in enumerate(FAQS):
        passages.append({"id": f"faq-{i}", "title": f"Question: {question}", "label": question,
                         "url": "/services#questions", "text": answer})
    passages.append({
        "id": "process", "title": "How we work: our process in four steps", "label": "How we work",
        "url": "/about#process",
        "text": " ".join(f"Step {i + 1}, {name}: {body}" for i, (name, body) in enumerate(STEPS)),
    })
    passages.append({
        "id": "about", "title": "About flowpath: who we are, where we are based, the team", "label": "About flowpath",
        "url": "/about",
        "text": "flowpath is a digital marketing studio started in 2019. "
                + ". ".join(f"{t}: {d}" for t, d in FACTS) + ". "
                + " ".join(f"{n}: {b}" for n, b in VALUES),
    })
    passages.append({
        "id": "roles", "title": "Open roles: jobs and careers at flowpath", "label": "Open roles",
        "url": "/about#roles",
        "text": "We are hiring for: " + " ".join(f"{t} ({w}): {b}" for t, w, b in ROLES)
                + f" Apply by email to {SITE['email']}.",
    })
    passages.append({
        "id": "contact", "title": "Contact flowpath: email, WhatsApp, phone, address, hours", "label": "Contact details",
        "url": "/contact",
        "text": f"Email {SITE['email']}. WhatsApp or call {SITE['phone']}. The studio is at {SITE['address']}. "
                "Open Monday to Friday, 10 am to 6 pm. We reply to every message within one working day. "
                "You can also send the contact form.",
    })
    return passages
