Use the playwright mcp to test the app end-to-end. Be methodical and take your time. Test all screens and controls. Test user workflows and edge cases. Use the frontend-design skill to assess the visual aesthetics of the UI. Assess user-friendliness and accessibility. Fix all bugs and provide suggestions for UI improvements.

Displaying raw HTML or unrendered markdown is considered a bug, except in the post editor text view. Ensure that all content is rendered correctly and looks good in the Web UI. Check for broken links.

Make sure to test user workflows involving:
- uploading (multiple) images and embedding them in posts,
- adding, editing and viewing posts with complex markdown: tables, multiple headings on different levels with references, math formulas, images, block quotations, code syntax highlighting in code blocks, complex lists with multiple level sublists, checkbox lists,
- table of contents for long posts,
- internal and external links in posts,
- support for ALL of pandoc markdown (read docs/pandoc/08-pandocs-markdown.md) and whether it renders correctly and looks good in the Web UI,
- non-english characters, unicode,
- invalid input (e.g. invalid markdown, spaces in labels, invalid title or author, cycles in label graph),
- managing files associated with posts,
- label editing,
- post search and filtering,
- sharing posts on social media platforms,
- cross-posting,
- dark mode,
- user authentication and authorization,
- admin panel operations.
