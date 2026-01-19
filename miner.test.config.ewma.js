module.exports = {
  apps: [
    {
      name: "miner",
      interpreter: "./venv/bin/python3",
      script: "./neurons/miner.py",
      args: "--netuid 247 --logging.debug --logging.trace --subtensor.network test --wallet.name duke524 --wallet.hotkey synth_miner_ewma_0 --axon.port 8091 --blacklist.validator.min_stake 0",
      cwd: "/root/sn50/synth_miner_ewma/synth-subnet",
      env: {
        PYTHONPATH: "/root/sn50/synth_miner_ewma/synth-subnet",
      },
    },
  ],
};
