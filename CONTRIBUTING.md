# Contributing to TraitTrawler

Thanks for your interest in contributing! TraitTrawler is an open project and we welcome contributions of all kinds.

## Ways to contribute

### Report a bug or extraction error

If TraitTrawler extracted incorrect data for a species you know about, [open an issue](https://github.com/coleoguy/TraitTrawler/issues/new?template=data_error.yml) with the species name, the incorrect value, the correct value, and a citation to the primary source.

### Share a new taxon configuration

If you've adapted TraitTrawler for a different organism or trait, we'd love to include it as an example configuration. Submit a pull request adding a directory under `examples/` with your three config files (`collector_config.yaml`, `config.py`, `guide.md`) and a brief README describing the system.

### Improve the agent

Bug fixes, validation rule improvements, and documentation improvements are welcome as pull requests. For larger changes, please open an issue first to discuss the approach.

## Pull request guidelines

1. Fork the repository and create a feature branch from `main`
2. Keep changes focused: one logical change per pull request
3. For data corrections, include a citation to the primary source
4. For code changes, test with at least one extraction session before submitting

## Code of conduct

Be kind and constructive. We're scientists trying to make data collection less painful.

## Questions?

Contact Heath Blackmon: coleoguy@gmail.com
