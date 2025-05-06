# /tmp Usage

This directory should be used for local development only. Everything in /tmp
is ignored (with the exception of this README) by the .gitignore file.

**IMPORTANT**: that does mean that nothing in /tmp will be backed up on
github, so make sure that if you put anything in here that you want to keep
when your computer dies, you back it up somewhere else.

## updating a jupyter notebook after source code changes

When you make changes to the source code, you can update a running jupyter
notebook with the new code by running the following command in a cell:

```python
import importlib
import tfbpmodeling

importlib.reload(tfbpmodeling.SigmoidModel)
```
