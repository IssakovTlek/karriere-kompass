# Germany Career Agent for Alizhan Nurzhan

This local AI agent finds **in-office or hybrid** opportunities within 40 km of Heidelberg, including Mannheim. It targets internships, working-student roles, and volunteering in business development, marketing, sales, customer acquisition, digital content, and practical AI.

It deliberately does **not** apply to jobs. Instead, it produces a reviewed shortlist and a tailored cover-letter draft for each strong match.

## Setup

1. Install Python 3.11 or newer.
2. Copy `.env.example` to `.env` and fill in the keys.
3. Run the agent (it uses only Python's standard library):

   ```powershell
   python agent.py run
   ```

Results are saved under `output/YYYY-MM-DD/`:

- `vacancies.json` - all collected and filtered roles
- `shortlist.json` - roles scored 70/100 or higher
- `applications/*.md` - tailored drafts to review and submit manually

## Keys

- `SERPAPI_API_KEY` is used to search Google Jobs in Germany. Create one at [SerpApi](https://serpapi.com/).
- `OPENAI_API_KEY` ranks vacancies and writes drafts. It is never written to output files.

The agent stops clearly when either key is missing. No vacancy, personal data, or application is submitted anywhere automatically.

## Search rules

- Centre: Heidelberg, Germany; maximum distance: 40 km.
- Allowed arrangements: office/on-site or hybrid.
- Rejected: fully remote/online roles.
- Allowed types: internship, working student/Werkstudent, volunteer/Ehrenamt.
- The source links in every result must be checked before applying: job boards can change or duplicate listings.

## Customization

Edit `profile.json` to update availability, university dates, languages, or preferred roles. Edit constants at the top of `agent.py` to change the radius or shortlist threshold.
