I want to create a web blogging platform AgBlogger with the following features / requirements. Create a plan to design and implement AgBlogger and write it to PLAN.md. Choose most appropriate technologies and architecture based on the requirements. Consider performance and ease of deployment. Take your time – this is a complex task.

- The blog posts are markdown-based. Markdown files are the ultimate source of truth. The app can use a lightweight relational database to speed up search, filtering, etc, but both post content and metadata are stored in markdown files. Metadata related to a post is specified in a YAML front matter block at the beginning of the post's markdown file. Config data not related to any specific post is stored in TOML files.
- All markdown (including YAML front matter) and TOML files are human-readable and human-editable.
- Special markdown files for "About" and other top-level pages (switchable by tabs at the top of the webpage). Top-level pages should be configurable via an `index.toml` file, including their order (the first one is the main page).
- Default main page: timeline of all posts. It should be possible to refer to the timeline page in `index.toml` if the user e.g. wants to not have it first (main).
- Relational database contains the following data not replicated elsewhere:
	- user account details,
	- authentication-related data.
- Database contains tables to speed up blog post search, filtering and categorization. These effectively function as caches of blog post YAML front matter metadata.
- Posts can have multiple labels.
	- Labels categorize posts, e.g., "cooking", "software engineering", "politics".
	- Labels:
		- identified by unique ids #label-id defined in TOML files (the label ids are bare keys under `labels`),
		- names of a label provide alternative ways to refer to a label, e.g., if #swe has "programming" as one of its names, then when selecting a label in the UI, providing "programming" selects the #swe label
		- example:
			```toml
			[labels]
				[labels.cs]
				names = ["computer science"]

				[labels.swe]
				names = ["software engineering", "programming", "software development"]
			    parent = "#cs"
			```
		- labels may be defined implicitly (not yet present in a TOML file) – referring to a new label with #label-id creates an entry for #label-id
	- Labels are organized in a directed acyclic graph (DAG). A label can have any number of parents (supercategories) and children (subcategories), as long as there are no cycles.
- Post metadata (YAML in front matter) contains:
	- date and time post created,
	- date and time post edited,
	- author (optional),
	- labels (optional),
	- date and time follow TIMESTAMPTZ format: `YYYY-MM-DD HH:MM:SS.ffffff±TZ`, but simpler date/time formats allowed with local/default timezone inferred and missing SS.ffffff set to zeros (lax input, strict output)
- Post title is the first main `#`-heading in the file (single `#` only). If not present, title derived from file name.
- Example blog post markdown file with YAML front matter:
	```markdown
	---
	created_at: 2026-02-02 22:21:29.975359+00
	modified_at: 2026-02-02 22:21:35.000000+00
	labels: [#swe, #ai]
	---
	# Title

	Blog post markdown content
	```
- Config data not connected directly with any single post stored in TOML files:
	- label definitions,
	- project-level (blog-level) preferences.
- Sync between a local directory containing blog posts in markdown and the blogging platform server.
	- It should in principle be possible to add/edit/delete posts with their metadata entirely locally by editing markdown files and then sync with the blogging platform server.
	- The sync is possible in both direction - also bring in changes from the server to local folder.
	- Intelligent conflict resolution which doesn't require user intervention in most cases.
	- The local directory may include other files than just markdown posts, e.g., image, PDF, binary, or other files. All files in the local directory and subdirectories (recursively) should be synced.
	- The local directory may contain subdirectories. All blog post markdown files in all subdirectories recursively should be considered as blog posts. Directory structure provides implicit label hierarchy (in addition to any other labels).
	- Sync is on demand (live sync not needed). Sync re-generates DB caches.
- Web rendering of markdown blog posts.
	- Crucial: rendering of KaTeX math enclosed by single dollar signs, e.g., `$\alpha$` in markdown rendered as greek letter alpha
	- Support for syntax highlighting for multiple programming languages with markdown code blocks. Ability to extend with custom language syntax highlighting rules for new / rare languages.
	- Rendering of inline images.
	- Embedding of inline videos.
	- Support local links within the directory structure.
	- Support for Github markdown extensions or similar.
	- Support for Quarto markdown extensions or similar.
	- Consider using `pandoc`.
- Editing/adding/removing posts via the platform's web interface.
	- Lightweight markdown editor component that renders consistently with web rendering of blog posts (consider reusing `react-md-editor`).
	- Authenticated users only.
	- Updates both markdown (source of truth) and DB caches.
- Editing/adding/removing labels
	- Updates both TOML (source of truth) and DB caches.
- Viewing and navigating the label graph. The label graph navigator also enables displaying all posts with a given label.
- Filtering by label, date, author.
- Cross-posting to X, Facebook, Bluesky, other popular platforms.
