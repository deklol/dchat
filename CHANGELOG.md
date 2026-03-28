# Changelog

## v1.3
- Added category-based live chatrooms with their own message feeds, participant rails, and the latest three related topics pinned at the top.
- Reworked chat message continuity so consecutive messages chain cleanly and only reset identity after a long gap or a speaker change.
- Moved chat message actions into a compact far-right hover affordance that no longer creates extra spacing between messages.
- Added Django admin controls for KLIPY integration through Site Branding, so operators can enable GIF search without editing env files.
- Removed the redundant top-nav Chatroom link and tightened the public README for a cleaner GitHub-facing release.

## v1.2
- Added lightweight live inbox badge updates so new DMs and inbox notifications appear without a full page refresh.
- Invalidated unread-count caches on DM send, DM read, mention read, and notification read for consistent header state.
- Added an Inbox Settings shortcut on the owner profile page.
- Linked the footer `dChat` brand text to the public GitHub repository through the outbound-link gate.
- Added per-conversation DM icons to the guild rail with a context menu action to hide chats from the rail.
- Brought DMs closer to thread capability parity with markdown/link embeds and multiple image uploads up to the normal 8 MB per-file limit.

## v1.1
- Replaced vote-derived "rep" with a real reputation system backed by explicit `+Rep` grants and moderator warning penalties.
- Added `+Rep` actions to thread starters and replies, with one grant per user per piece of content.
- Added moderator `Warn` actions that deduct rep and notify the warned user.
- Expanded the user popup card and profile page with live forum stats plus recent topics and replies.
- Fixed long topic subthread names in the sidebar with a stable two-line layout that keeps the meta column aligned.

## v1.0
- Added direct post permalinks: clicking a post timestamp now targets that exact post and copies its deep link.
- Added thread-level mention state in topic lists with unread mention badges/highlighting that clear when the thread is viewed.
- Added image-based thread creation rendered in the thread starter area for comment-driven image topics.
- Added nested left-sidebar subthreads showing active threads from the last 24 hours, including unread mention badges.
- Added encrypted direct messages with user-to-user conversations, report controls, and staff review access limited to reported DMs.
- Added DM action and online/offline status indicator to the user popup card.
- Fixed reply-card stat counters resetting to zero after live fragment refreshes.

## v0.9
- Removed the footer entirely and moved the useful app/legal/community information into cleaner right-sidebar modules.
- Added reusable sidebar blocks for community presence, newest user, recent activity, version, changelog, FAQ, and legal links.
- Removed the old footer refresh/clock client logic so the browser no longer polls footer fragments in the background.

## v0.8
- Moved the footer into the scrolling content flow so it behaves like a normal forum footer instead of a fixed app status bar.
- Kept the desktop and mobile shell height logic intact while removing the persistent bottom-row behavior.
- Added forum stats in the left author column for thread starters and replies, including posts, topics, and rep.
- Footer user links now trigger the same profile popup behavior as the rest of the app.
- Added a padded frame around embedded image previews and darkened the header to better match the shell.

## v0.7
- Fixed clipped top corners on thread and reply cards by tightening panel overflow and post shell treatment.
- Simplified the desktop workspace with lighter chrome, calmer spacing, cleaner type scale, and less aggressive panel shadows.
- Reworked the `dekcx` preset into a palette-only variant so it matches the modern layout instead of fighting it with retro borders and fonts.
- Added static asset cache-busting tied to the app version so CSS and JS updates show immediately after deploy.

## v0.6
- Rebuilt thread detail replies into a proper forum post layout with nested reply chains instead of flat chat rows.
- Added a working Markdown composer toolbar, visible reply submit flow, and direct reply targeting from each post.
- Added `@mention` autocomplete with lightweight inbox notifications that link straight back to the mentioned post or thread.
- Removed duplicate thread search from the home view and trimmed footer links down to the essentials.

## v0.5
- Rebuilt the default interface around a Discord-like workspace with a denser Zulip-style stream/topic layout.
- Reworked thread detail into a proper conversation view with a separate inspector for metadata and moderation actions.
- Redesigned auth, profile, moderation, changelog, docs, and external-link screens to match the main forum UI.
- Replaced the footer with a sticky forum-style information block that still fits the dark app theme.

## v0.4
- Reworked default UI to a Discord-first shell with Zulip-inspired information density.
- Added a proper app frame with guild rail, stream sidebar, focused message pane, and compact top bar.
- Redesigned thread and reply presentation for a closer Discord-style conversation flow.
- Upgraded user popup card styling and profile sections for faster identity scanning.

## v0.3
- Added optional `dekcx` theme preset inspired by a Habbo archive visual language.
- Added theme preset controls in Site Branding admin with one-click preset palette apply.
- Preserved full custom color token editing while `dekcx` is active.

## v0.2
- Added SSE realtime for thread and presence updates.
- Added moderation queue, reporting, soft delete/restore, and moderation logs.
- Added GDPR export and account/content deletion workflow.
- Added outbound link warning gateway and hardened security headers.
- Added backup/restore scripts, health checks, and metrics endpoint.

## v0.1
- Initial dChat scaffold with setup wizard, auth, forum basics, uploads, and admin structure.
