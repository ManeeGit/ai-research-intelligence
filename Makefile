.PHONY: demo serve test evaluate check

demo:
	python3 -m research_agent demo

serve:
	python3 -m research_agent serve

test:
	python3 -m unittest discover -s tests -v

evaluate: demo
	python3 -m research_agent evaluate

check: test evaluate
	python3 -m compileall -q research_agent tests
	node --check research_agent/static/app.js
