import time
from providers.base import BotProvider

MOCK_TRANSCRIPT = """
[00:00:03] Sarah: Okay I think we're mostly here, let me just — can everyone hear me alright? Marcus, you good?

[00:00:08] Marcus: Yeah I can hear you. Priya's still showing as connecting on my end though.

[00:00:12] Priya: No I'm here, I'm here. Sorry, my headset died, I'm just on laptop audio. Can you hear me okay?

[00:00:17] Sarah: Yeah you're coming through fine. Okay let's just get started, Jake said he'll be a few minutes late, he's finishing up a deploy.

[00:00:24] Marcus: Cool. Elena, you joining today or is she—

[00:00:27] Elena: I'm here, sorry, I was muted. Hi everyone.

[00:00:30] Sarah: Great, okay so we've got a lot to cover today. I want to do a quick sprint review, then get into the API performance stuff because I know Marcus flagged that as urgent, then we need to make a call on the dashboard redesign timeline, and I also want to leave time at the end to talk about the Hendricks account situation. Tom said he might drop in for that last piece.

[00:00:52] Marcus: Yeah Tom mentioned that to me too. He's in back-to-backs until eleven so probably won't make the first half.

[00:00:58] Sarah: Okay that's fine. So let's start with sprint review. Priya, you want to kick us off? What actually shipped this week?

[00:01:06] Priya: Sure yeah. So the big one was the bulk export feature — that's fully live in production as of yesterday afternoon. We had a small regression in the CSV formatting that Jake caught in staging, so good catch there, that got fixed before it went out.

[00:01:21] Jake: [joins] Hey sorry, just got on, did I miss much?

[00:01:24] Sarah: No perfect timing, Priya's just doing sprint review.

[00:01:27] Priya: Hey Jake. Yeah so — bulk export is live, the notification preferences refactor is done on the backend, frontend's still in progress on that one. The rate limiting changes Marcus asked for on the public API, those are also live. And then the OAuth flow bug that's been open since like March — that's finally fixed.

[00:01:46] Marcus: Oh that OAuth thing went out? I didn't see it in the release notes.

[00:01:50] Priya: Yeah Darren merged it Thursday I think, it might have gone out in a hotfix. Let me — actually I'll drop the PR link in Slack after this.

[00:01:58] Marcus: Yeah please do, because we've got at least two customers who reported that issue and I want to make sure support follows up with them.

[00:02:05] Sarah: Good catch. Okay what didn't ship? What's carrying over?

[00:02:09] Jake: The notification preferences UI is mine, that's carrying over. I ran into some issues with the state management, basically the way we had the Redux slice set up was going to make it really hard to do the per-channel granularity that the spec called for. So I refactored that whole thing, which took longer than expected, but it's in a much better place now. Should be done by Tuesday.

[00:02:32] Sarah: Okay. Is that going to block anything?

[00:02:35] Jake: Not really, it's a standalone feature. The only dependency is if we want to announce it alongside the mobile push notification stuff, but I think those are on different timelines anyway.

[00:02:45] Priya: Yeah the mobile push stuff is Q3, we're fine.

[00:02:48] Sarah: Alright. What else is carrying over?

[00:02:51] Marcus: The database index changes. I wanted to get those in this sprint but we needed a maintenance window and the one we had scheduled got pushed because of that incident last Tuesday. So that's next sprint, it's on me to coordinate with infra.

[00:03:05] Sarah: Right yeah. Okay that actually is a good segue into the API performance stuff. Marcus, you want to take this?

[00:03:12] Marcus: Yeah so — and this is kind of the thing I've been most worried about this week. We've been seeing some pretty significant latency spikes on the reporting endpoints. Like p99 is sitting around four seconds on the weekly summary queries and that's up from like eight hundred milliseconds two weeks ago.

[00:03:30] Sarah: Okay wait, four seconds? That's bad.

[00:03:33] Marcus: It's bad. And the thing is it's not uniform, it's specifically the enterprise accounts with large datasets. So like the Hendricks account, the Nakamura account, a couple others. These are our biggest customers.

[00:03:46] Priya: Is this the same thing as what got flagged in the Hendricks ticket last week or is this a separate issue?

[00:03:52] Marcus: Related but not exactly the same. The Hendricks ticket was specifically about the custom date range reports timing out. What I'm seeing now is more general — it's the standard weekly reports as well, just on large accounts. I think they're both symptoms of the same underlying thing which is that we don't have proper indexes on the events table for the query patterns we're actually using.

[00:04:14] Priya: Yeah I looked at the slow query logs on Friday and it's doing full table scans on the events table for anything that filters by account_id and date range together. Like we have an index on account_id and we have an index on created_at separately but not a composite index.

[00:04:30] Marcus: Exactly. And the events table is now at — I checked this morning — it's at about 340 million rows across all accounts. So full table scans are just not viable anymore.

[00:04:41] Jake: How long would adding the composite index take?

[00:04:44] Marcus: Adding it is fast. The problem is building it on a 340 million row table in production is going to be slow and will lock the table, so we need to do it during a maintenance window. We can use CREATE INDEX CONCURRENTLY in Postgres which avoids the lock but it still takes time and puts load on the database.

[00:05:01] Priya: I've done this before on a similar sized table at my last job. It took about two hours with concurrent indexing, but the database was under normal load the whole time, no customer impact.

[00:05:11] Marcus: Yeah that's roughly what I'd expect. So my proposal is we schedule a maintenance window for this coming Sunday at like two AM, I'll coordinate with DevOps, we run the index creation concurrently, and we monitor it. I'd want Priya on call that night just in case.

[00:05:27] Priya: Yeah I can do that.

[00:05:29] Sarah: Okay is this the only fix or are there other things we need to do?

[00:05:33] Marcus: There are a few things. The index is the main one and will probably solve like 80% of the problem. But we should also look at whether we can cache the results of these weekly summary queries because honestly they're expensive to compute and the data doesn't change that frequently — like for a completed week the numbers are never going to change, so we could cache aggressively.

[00:05:53] Priya: We'd need to be careful with the invalidation logic. If someone modifies a past event, which does happen, the cache would be stale.

[00:06:02] Marcus: True. We could do a time-based TTL, like cache for 24 hours, and accept that the numbers might be slightly stale. Or we do event-based invalidation but that's more complex.

[00:06:12] Jake: What does the product spec say about freshness? Like do we actually promise real-time data on these reports?

[00:06:18] Sarah: Good question. I don't think we do explicitly, but customers probably expect it. Elena, you know anything about what we've communicated to customers about this?

[00:06:27] Elena: I mean not from a product communication standpoint, but the UI doesn't show any kind of "last updated" timestamp or anything like that. So customers probably do assume it's real-time.

[00:06:38] Sarah: Okay so we should probably not silently introduce caching without at least showing when the report was last generated.

[00:06:45] Marcus: Yeah that's fair. That's actually a quick UI change — just add a "generated at" timestamp to the report header.

[00:06:52] Elena: I can mock that up today, it's like a one-line addition to the report header component. Should be in the design system already.

[00:06:59] Jake: Yeah I can implement that in like an hour once Elena drops the mock.

[00:07:03] Sarah: Okay so let's make that a thing. The index is the priority for performance, Elena mocks the timestamp UI today, Jake implements it, and then we can enable caching behind a feature flag to start. Marcus, does that work?

[00:07:16] Marcus: Yeah that works. I'd say let's do 6-hour TTL to start, see how it goes.

[00:07:21] Sarah: Okay. Who owns the caching implementation?

[00:07:24] Priya: I can take that. It's probably a Redis integration, we already have Redis in the stack for sessions so it's not a new dependency.

[00:07:32] Marcus: Perfect. So to summarize this piece: Priya and I are doing the index Sunday night, Priya also owns the caching implementation, Elena is doing the timestamp UI mock today, Jake is implementing it. I'd say let's target having the caching in staging by end of next week.

[00:07:48] Sarah: Great. Okay let's talk about the dashboard redesign. Elena, this is mostly yours.

[00:07:54] Elena: Yeah so — okay where do I even start. So we've been working on the new dashboard for about six weeks now and I feel like we're in a good place on the designs, I'm really happy with where it landed. But the timeline is where I'm stressed. The original plan was to ship this before the user conference in September, which is September 14th.

[00:08:17] Sarah: Yeah.

[00:08:18] Elena: And I just — looking at what's left, I'm not sure we can make that. Like the core views are designed and in handoff. But we still have the customization layer, the widget library, and the permission-based view stuff which is actually really complex.

[00:08:32] Marcus: How complex is the permissions piece?

[00:08:35] Elena: So the idea is that admins can configure which metrics are visible to which roles. Like a sales manager sees different widgets than an ops person. And the data model for that is — I think it's pretty involved. Right, Priya?

[00:08:48] Priya: Yeah I scoped it out a few weeks ago. It's roughly three to four weeks of backend work. And then probably another two or three weeks of frontend to wire it all up.

[00:08:58] Jake: And that's assuming the design is fully locked down before we start, otherwise it's going to be longer.

[00:09:04] Elena: The designs won't be fully locked until end of this week at the earliest. I'm still iterating on the widget customization flow.

[00:09:11] Sarah: Okay so realistically if designs are done by Friday, and we start dev next Monday, and it's like six weeks of work—

[00:09:18] Marcus: We're looking at late July for the full thing. And that doesn't include QA time or any buffer for things going wrong.

[00:09:26] Sarah: Which means we would not make September 14th with the full feature.

[00:09:30] Elena: Right. Which is what I've been trying to flag for a couple weeks now but—

[00:09:34] Sarah: No I know, I know. I should have escalated this sooner. Okay so what are our options? Like what could we ship by September 14th?

[00:09:42] Marcus: We could ship the core views without the customization layer. Like the new design, the new layout, better charts — all of that. Just without the permissions stuff and the drag-and-drop widget customization.

[00:09:55] Jake: That would actually be a much smaller scope. Like the core views and the widget library without customization is maybe three weeks of work.

[00:10:02] Elena: And honestly the new design itself is a significant improvement even without the customization. The charts are way better, the layout makes more sense, the mobile experience is dramatically improved.

[00:10:13] Sarah: Would customers notice what's missing?

[00:10:16] Marcus: I mean some would. The power users who are currently doing weird workarounds to customize their dashboards — they would notice and they would not be happy.

[00:10:25] Sarah: How many customers are actively using the current customization features?

[00:10:30] Elena: I looked at the analytics last week. It's like twelve percent of accounts have made any customization to their default dashboard. And of those, most of them have just changed the date range default. The actual widget rearrangement feature is used by maybe three percent of accounts.

[00:10:46] Sarah: Okay so three percent. That's not nothing but it's also not the majority.

[00:10:51] Marcus: And we could keep the old customization UI alive for those users while the new one is being built. Like a "switch to new dashboard" toggle that defaults to the new design but lets you go back.

[00:11:02] Jake: That would add some complexity though. Maintaining two dashboard codebases even temporarily is annoying.

[00:11:08] Marcus: Yeah but it's probably less annoying than delaying the whole thing by two months.

[00:11:13] Sarah: What does Tom think about this? Has anyone talked to him?

[00:11:16] Marcus: Not specifically about the timeline. He knows there's a redesign coming, I don't think he knows the customization piece is at risk.

[00:11:23] Sarah: Okay I need to talk to him today. Let me — can we make a decision here or do we need Tom to weigh in?

[00:11:30] Marcus: I think we can make a recommendation and then run it by Tom. My recommendation is we ship the core redesign in September without the customization layer, maintain the old dashboard as a fallback for the three percent, and ship the full customization in Q4.

[00:11:45] Priya: That seems right to me. The core redesign is the value, the customization is nice to have.

[00:11:50] Jake: Agreed.

[00:11:51] Elena: Yeah I think that's the right call. I just want to make sure we actually commit to the Q4 date for customization and it doesn't keep slipping.

[00:11:59] Sarah: Agreed. Okay so let's call that the plan — I'll validate with Tom today. Elena, can you have designs wrapped up by Friday so we can start dev Monday?

[00:12:08] Elena: Yes, I'll prioritize. The widget customization designs can be parked for now anyway.

[00:12:14] Sarah: Perfect. Marcus, can you write up the phased rollout plan? Like what's in September, what's in Q4, how the toggle works?

[00:12:21] Marcus: Yeah I'll do that by Wednesday.

[00:12:23] Sarah: Great. Okay last thing — the Hendricks account. Oh, Tom just joined actually.

[00:12:29] Tom: Hey everyone, sorry I'm late, what did I miss?

[00:12:32] Sarah: Hey Tom. We covered sprint review, the API performance stuff — Marcus can fill you in — and we just made a call on the dashboard redesign timeline, I'll catch you up on that after. Right now we're about to talk about Hendricks.

[00:12:44] Tom: Perfect, that's why I'm here. So — where are we with them?

[00:12:48] Sarah: Marcus, you want to give the quick background?

[00:12:51] Marcus: Sure. So Hendricks is one of our biggest enterprise accounts, they're on the Professional plan, about $84k ARR. They have a very large dataset — they've been on the platform for three years and they've got something like 40 million events. The issues they've been experiencing are related to what we were just talking about with the API performance — slow report generation, some timeouts on custom date range queries. Their CSM has been fielding complaints for about two weeks.

[00:13:18] Tom: Have we been in communication with them directly or just through the CSM?

[00:13:22] Sarah: Their CSM, Rachel, has been managing it. They haven't escalated to us directly yet but Rachel flagged to me that they're getting frustrated and there's a risk to renewal — they're up for renewal in October.

[00:13:34] Tom: October. Okay. So we've got maybe three months.

[00:13:37] Marcus: The good news is the fix is in progress — that's the index change we're doing Sunday night, plus the caching work. I'd expect their performance issues to be largely resolved by next week.

[00:13:48] Tom: But they don't know that yet.

[00:13:50] Sarah: Right. The question is how do we handle the communication. Do we proactively reach out and apologize and explain what we're doing, or do we wait until the fix is in and then tell them?

[00:14:01] Tom: We reach out now. You never want a customer to find out you fixed something after the fact without telling them you knew about it. That erodes trust way more than the original problem.

[00:14:12] Marcus: Agreed. I can write up a technical summary of what happened and what we're doing — the index issue, why it happened as the dataset grew, what we're doing to fix it, and when they can expect improvement.

[00:14:24] Tom: Good. And I think I should send the outreach personally, or at minimum co-sign it. This is a tier-one account, they should hear from leadership, not just the CSM.

[00:14:33] Sarah: That would be really good actually. I'll coordinate with Rachel so she knows it's coming and isn't caught off guard.

[00:14:39] Tom: Yeah please do. And let's think about whether there's anything we can offer them. Performance issues for two weeks on an enterprise account — is there anything from a service credit standpoint or a feature access standpoint that makes sense?

[00:14:52] Sarah: I don't want to automatically offer a credit because I think it sets a precedent, but I think we should be open to it if they ask. What if we offer them early access to the new dashboard redesign? It's something tangible and actually valuable.

[00:15:05] Tom: I like that. Early access, white-glove onboarding onto the new dashboard, personal check-in once the performance fix is in. That feels right.

[00:15:14] Marcus: I can also offer them a dedicated performance review — like get on a call with them and walk through their specific query patterns and make sure they're getting the best possible performance from the platform.

[00:15:25] Tom: Yeah. That's the kind of thing that turns a frustrated customer into an advocate. Okay so who's doing what here?

[00:15:31] Sarah: Marcus writes the technical summary by end of today. I'll draft the outreach email for Tom to send, and I'll loop in Rachel. Marcus, you're available for the performance review call whenever they want to schedule it?

[00:15:43] Marcus: Yeah, just give me some notice. Anything after Wednesday works.

[00:15:47] Tom: Good. And I'd like to send the email today if possible, Sarah. Can you have a draft to me by two?

[00:15:53] Sarah: I can do that, yeah.

[00:15:55] Tom: Perfect. Thanks everyone, I have to jump. Good work on the performance investigation Marcus, Priya.

[00:16:01] Marcus: Thanks Tom.

[00:16:02] Priya: Thanks.

[00:16:04] Tom: [leaves]

[00:16:06] Sarah: Okay, let's wrap up. Let me just do a quick read-back of action items so we're all aligned.

Marcus: index change Sunday night, you're coordinating with DevOps and Priya is on call. You're also writing the dashboard phased rollout plan by Wednesday, the technical summary for Hendricks by end of today.

Priya: on call Sunday for the index, and you own the caching implementation — target staging by end of next week.

Elena: dashboard designs wrapped up by Friday, and the report timestamp UI mock by end of today.

Jake: implement the timestamp UI once Elena has the mock, should be done same day or tomorrow.

Me: I'm drafting the Hendricks outreach email for Tom by two, looping in Rachel, and I'm talking to Tom today about the dashboard timeline decision.

Did I miss anything?

[00:16:58] Marcus: I don't think so. Oh actually — I wanted to flag one more thing quickly. We're getting close to our Postgres storage limits. We're at like 78% capacity. It's not urgent but we should plan for either archiving old data or upgrading the storage tier in the next month or so.

[00:17:15] Sarah: Okay let's not solve that right now but Marcus can you put together a quick options doc? Like what does archiving look like, what does storage upgrade cost, what's the tradeoff?

[00:17:24] Marcus: Yeah I'll add that to my list. I can have something by end of next week.

[00:17:28] Sarah: Thanks. Okay, I think that's everything. Good meeting everyone, thanks for the time.

[00:17:33] Priya: Thanks.

[00:17:34] Jake: Later everyone.

[00:17:35] Elena: Bye!

[00:17:36] Marcus: See you all.
""".strip()

# Simulated delay for advanced (email) flow in seconds.
# Mimics Vexa waiting for a calendar invite before joining.
MOCK_EMAIL_FLOW_DELAY = 10


class MockBotProvider(BotProvider):
    """Mock provider for tests and demos. URL flow is instant; email flow simulates async delay."""

    def __init__(self):
        # Tracks when email-flow meetings were registered { meeting_id: registered_at }
        self._email_meetings: dict[str, float] = {}

    def join_by_url(self, url: str, meeting_id: str) -> str:
        """URL flow: bot joins instantly, transcript is immediately available."""
        return meeting_id

    def join_by_email(self, email: str, meeting_id: str) -> str:
        """
        Email flow: register the meeting as 'waiting for invite'.
        Transcript becomes available after MOCK_EMAIL_FLOW_DELAY seconds,
        mimicking Vexa watching an inbox and auto-joining on invite arrival.
        """
        self._email_meetings[meeting_id] = time.time()
        return meeting_id

    def is_transcript_ready(self, meeting_id: str) -> bool:
        """
        For URL-flow meetings: always ready.
        For email-flow meetings: ready only after the simulated delay.
        """
        if meeting_id not in self._email_meetings:
            return True  # URL flow — always ready
        elapsed = time.time() - self._email_meetings[meeting_id]
        return elapsed >= MOCK_EMAIL_FLOW_DELAY

    def get_transcript(self, meeting_id: str) -> str:
        """Return transcript only if ready, empty string otherwise."""
        if not self.is_transcript_ready(meeting_id):
            return ""
        return MOCK_TRANSCRIPT

    def health(self) -> dict:
        return {"status": "ok", "detail": "Mock provider — no external dependency."}
