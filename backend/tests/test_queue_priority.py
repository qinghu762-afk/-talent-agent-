from kombu.utils.scheduling import cycle_by_name


def test_real_transport_strategy_keeps_control_and_matching_ahead_of_bulk_work():
    from talent.worker import celery_app

    strategy = celery_app.conf.broker_transport_options["queue_order_strategy"]
    cycle = cycle_by_name(strategy)()
    # Redis transport supplies a set, so CLI -Q order cannot be relied on.
    cycle.update(["ingest", "index", "match", "control"])
    assert cycle.consume(4) == ["control", "match", "index", "ingest"]
    cycle.rotate("control")
    assert cycle.consume(4) == ["control", "match", "index", "ingest"]
