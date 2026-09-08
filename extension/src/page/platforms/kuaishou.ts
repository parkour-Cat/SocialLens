// 快手 page actions. API notes: docs/platforms/kuaishou.md
// Two generations of the site coexist: the old UI (home, video page) uses one GraphQL endpoint
// (captures told apart by operationName via "url @@ body" patterns) and server-renders into
// window.__APOLLO_STATE__; the new UI (search, profile) uses REST under /rest/v/ and
// server-renders into window.INIT_STATE. The site issues its own requests (navigate).

import { PageError } from "../errors";
import { firstOrMore, more } from "./navigate";
import type { PageAction, PagePlatform } from "./types";

const GQL = "/graphql";
const op = (name: string) => `${GQL} @@ "operationName":"${name}"`;

const searchPosts: PageAction = async (p, ctx) => firstOrMore(p, ctx, "/rest/v/search/feed");
const searchUsers: PageAction = async (p, ctx) => firstOrMore(p, ctx, "/rest/v/search/user");
const getPost: PageAction = async (p, ctx) => {
  // The video page is server-rendered (old UI): the detail sits in window.__APOLLO_STATE__.
  const state = (await ctx.readGlobal("__APOLLO_STATE__.defaultClient", 15_000)) as Record<string, Record<string, unknown>>;
  const id = String(p.id ?? "");
  const photoKey = Object.keys(state).find((k) => k === `VisionVideoDetailPhoto:${id}`) ?? Object.keys(state).find((k) => k.startsWith("VisionVideoDetailPhoto:"));
  const authorKey = Object.keys(state).find((k) => k.startsWith("VisionVideoDetailAuthor:"));
  if (!photoKey) throw new PageError("not_found", `video ${id} not in page state (deleted, private, or page changed)`);
  const tags = Object.entries(state).filter(([k, v]) => k.includes(".tags.") && v && typeof v === "object").map(([, v]) => (v as { name?: string }).name).filter(Boolean);
  return { ssr: true, photo: state[photoKey], author: authorKey ? state[authorKey] : null, tags, href: location.href };
};
const getComments: PageAction = async (p, ctx) => firstOrMore(p, ctx, op("commentListQuery"));
const getUser: PageAction = async (p, ctx) => {
  // The profile page (new UI) is server-rendered into window.INIT_STATE, keyed by obfuscated
  // request paths; the entry we want is the one carrying `userProfile`.
  const state = (await ctx.readGlobal("INIT_STATE", 15_000)) as Record<string, unknown>;
  const entry = Object.values(state).find((v) => v && typeof v === "object" && "userProfile" in (v as object)) as { userProfile?: unknown } | undefined;
  if (!entry?.userProfile) throw new PageError("not_found", "user profile not in page state (deleted, banned, or page changed)");
  return { ssr: true, user: entry.userProfile, href: location.href };
};
const getUserPosts: PageAction = async (p, ctx) => (p.more ? more(ctx, "/rest/v/profile/feed") : firstOrMore(p, ctx, "/rest/v/profile/feed"));
const getFeed: PageAction = async (p, ctx) => firstOrMore(p, ctx, `${GQL} @@ /"operationName":"(brilliantDataQuery|visionNewRecoFeed|brilliantTypeDataQuery)"/`);

export const kuaishouPage: PagePlatform = {
  id: "kuaishou",
  hosts: [".kuaishou.com"],
  riskSignals: [/captcha\.zt\.kuaishou\.com/, /\/rest\/infra\/captcha/],
  actions: {
    search_posts: searchPosts,
    search_users: searchUsers,
    get_post: getPost,
    get_comments: getComments,
    get_user: getUser,
    get_user_posts: getUserPosts,
    get_feed: getFeed,
  },
};
