PYTHON ?= python
CONSTRAINTS ?= constraints-verified.txt
M5_ZIP ?= data/raw/m5-forecasting-accuracy.zip
AMAZON_DATA_DIR ?= data/raw/amazon-last-mile
AMAZON_ROUTE_JSON ?= $(AMAZON_DATA_DIR)/model_build_inputs/route_data.json
AMAZON_PACKAGE_JSON ?= $(AMAZON_DATA_DIR)/model_build_inputs/package_data.json
AMAZON_MART_DIR ?= data/processed/amazon-last-mile

.PHONY: install install-dev capabilities format lint test smoke full advanced advanced-check m5 download-amazon-routes prepare-amazon-route-marts validate build serve docker docker-smoke clean

install:
	$(PYTHON) -m pip install --constraint $(CONSTRAINTS) -e ".[full]"

install-dev:
	$(PYTHON) -m pip install --constraint $(CONSTRAINTS) -e ".[full,dev]"

capabilities:
	$(PYTHON) -m heavy_bulky.cli capabilities

format:
	$(PYTHON) -m ruff format src scripts tests

lint:
	$(PYTHON) -m ruff format --check src scripts tests
	$(PYTHON) -m ruff check src scripts tests


smoke:
	$(PYTHON) -m heavy_bulky.cli full-pipeline --config configs/smoke.yaml

full:
	$(PYTHON) -m heavy_bulky.cli full-pipeline --config configs/full.yaml

advanced:
	$(PYTHON) -m heavy_bulky.cli full-pipeline --config configs/full_advanced.yaml

advanced-check:
	$(PYTHON) scripts/run_advanced_service_validation.py --device auto --epochs 4

m5:
	$(PYTHON) scripts/run_m5_validation.py --m5-zip $(M5_ZIP) --output-dir outputs/m5_small

download-amazon-routes:
	bash scripts/download_amazon_routes.sh "$(AMAZON_DATA_DIR)"

prepare-amazon-route-marts:
	$(PYTHON) scripts/prepare_amazon_route_marts.py \
		--route-json "$(AMAZON_ROUTE_JSON)" \
		--package-json "$(AMAZON_PACKAGE_JSON)" \
		--out "$(AMAZON_MART_DIR)"

validate:
	PYTHON=$(PYTHON) CONSTRAINTS=$(CONSTRAINTS) bash scripts/run_full_validation.sh

build:
	$(PYTHON) -m build --wheel

serve:
	uvicorn heavy_bulky.api:app --host 0.0.0.0 --port 8000

docker:
	docker build -t heavy-bulky-delivery-reliability:0.4.3 .

docker-smoke:
	mkdir -p outputs/docker-smoke
	docker run --rm --user "$$(id -u):$$(id -g)" -e HOME=/tmp \
		-v "$(CURDIR)/outputs/docker-smoke:/app/outputs" \
		heavy-bulky-delivery-reliability:0.4.3

test:
	$(PYTHON) -m pytest --cov=heavy_bulky --cov-report=term-missing

clean:
	find outputs -mindepth 1 ! -name .gitkeep -exec rm -rf {} +
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type f -name '*.py[co]' -delete
	rm -rf build dist artifacts/dist *.egg-info src/*.egg-info .pytest_cache .ruff_cache htmlcov .coverage
