// X page actions. API notes: docs/platforms/x.md
// The site issues GraphQL calls at /i/api/graphql/{queryId}/{OperationName}; the queryId part
// changes with deployments, so captures match on the operation name at the end of the path.

import { firstOrMore, more } from "./navigate";
import type { PageAction, PagePlatform } from "./types";

const op = (name: string) => `/\\/graphql\\/[^/]+\\/${name}(\\?|$)/`;

const searchPosts: PageAction = async (p, ctx) => firstOrMore(p, ctx, op("SearchTimeline"));
const searchUsers: PageAction = async (p, ctx) => firstOrMore(p, ctx, op("SearchTimeline"));
const getPost: PageAction = async (p, ctx) => ctx.waitCapture(op("TweetDetail"), typeof p.since === "number" ? p.since : 0);
const getComments: PageAction = async (p, ctx) => firstOrMore(p, ctx, op("TweetDetail"));
const getUser: PageAction = async (p, ctx) => ctx.waitCapture(op("UserByScreenName"), typeof p.since === "number" ? p.since : 0);
// The profile timeline operation was renamed (UserTweets -> UserOriginalsTimeline); accept both.
const USER_POSTS = op("User(Tweets|OriginalsTimeline)");
const getUserPosts: PageAction = async (p, ctx) => (p.more ? more(ctx, USER_POSTS) : firstOrMore(p, ctx, USER_POSTS));
const getFeed: PageAction = async (p, ctx) => firstOrMore(p, ctx, op("HomeTimeline"));
// Replies to a reply: the reply's own TweetDetail page. Trending: explore timeline operations.
const getReplies: PageAction = async (p, ctx) => firstOrMore(p, ctx, op("TweetDetail"));
const getTrending: PageAction = async (p, ctx) => ctx.waitCapture(op("(ExplorePage|GenericTimelineById|ExploreSidebar|TrendingTimeline)"), typeof p.since === "number" ? p.since : 0);

export const xPage: PagePlatform = {
  id: "x",
  hosts: [".x.com", "x.com"],
  riskSignals: [/x\.com\/i\/flow\/login/, /x\.com\/account\/access/],
  actions: { search_posts: searchPosts, search_users: searchUsers, get_post: getPost, get_comments: getComments, get_user: getUser, get_user_posts: getUserPosts, get_feed: getFeed, get_replies: getReplies, get_trending: getTrending },
};
