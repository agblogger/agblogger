We need to stress-test the server under parallel load. First, start the dev server with `just start`. Then create 11 sonnet agents to simulate concurrent requests: 1 admin and 10 readers. The agents should send requests to the server concurrently and measure the server's performance under load. The requests should simulate user behavior, such as browsing articles, creating and editing blog posts, browsing and editing labels, searching and filtering, post sharing, admin panel operations. The agents should systematically test complex usage scenarios, including atypical concurrent edge cases. 

**IMPORTANT** You need to coordinate the agents to ensure proper testing of concurrent workflows and read/write contention. Simulate edge case scenarios of parallel server requests from different agents. Re-launch agents when testing a new concurrent usage scenario. Coordinate the agents to ensure that usage is indeed concurrent.

Make sure that all server API endpoints are covered and tested. In particular, make sure that the following scenarios are tested:
- admin edits and saves a blog post while multiple readers are simultaneously viewing it,
- admin deletes a blog post while multiple readers are simultaneously viewing it,
- readers try to access blog posts which have just been deleted by the admin,
- admin deletes or edits labels which the readers are concurrently searching for,
- admin deletes a post while readers are concurrently searching and filtering matching posts,
- admin sets a post to draft with multiple users concurrently viewing, searching or navigating to the post,
- readers share a post whose title has just been changed by the admin,
- readers share a post that has just been deleted by the admin,
- admin changes post author display name while readers are concurrently viewing, searching and navigating posts.

Make sure that requests are sent concurrently simulating multiple users accessing the server simultaneously. Each agent should assess the server's performance, identify any bottlenecks or issues, and report any problems or failures. The agents should run for a long time to simulate real user workflows, with multiple concurrent users accessing the server simultaneously. The agents should assess the correctness of the server's responses, and report on any discrepancies with frontend expectations.

When finished, stop the server with `just stop`.
