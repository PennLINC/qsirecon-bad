.. include:: links.rst

------------------------
Contributing to qsipost
------------------------

This document explains how to prepare a new development environment and
update an existing environment, as necessary.

Development in Docker is encouraged, for the sake of consistency and
portability.
By default, work should be built off of `pennlinc/qsipost:latest
<https://hub.docker.com/r/pennlinc/qsipost/>`_ (see the
installation_ guide for the basic procedure for running).


Patching working repositories
=============================
In order to test new code without rebuilding the Docker image, it is
possible to mount working repositories as source directories within the
container.
The ``qsipost-docker`` script simplifies this for the most common repositories::

    -f PATH, --patch-qsipost PATH
                          working qsipost repository (default: None)
    -p PATH, --patch-nipype PATH
                          working nipype repository (default: None)

For instance, if your repositories are contained in ``$HOME/projects``::

    $ qsipost-docker -f $HOME/projects/qsipost/qsipost \
                      -p $HOME/projects/nipype/nipype \
                      -i pennlinc/qsipost:latest \
                      $HOME/fullds005 $HOME/dockerout participant

Note the ``-i`` flag allows you to specify an image.

When invoking ``docker`` directly, the mount options must be specified
with the ``-v`` flag::

    -v $HOME/projects/qsipost/qsipost:/usr/local/miniconda/lib/python3.10/site-packages/qsipost:ro
    -v $HOME/projects/nipype/nipype:/usr/local/miniconda/lib/python3.10/site-packages/nipype:ro

For example, ::

    $ docker run --rm -v $HOME/fullds005:/data:ro -v $HOME/dockerout:/out \
        -v $HOME/projects/qsipost/qsipost:/usr/local/miniconda/lib/python3.10/site-packages/qsipost:ro \
        pennlinc/qsipost:latest /data /out/out participant \
        -w /out/work/

In order to work directly in the container, pass the ``--shell`` flag to
``qsipost-docker``::

    $ qsipost-docker --shell $HOME/fullds005 $HOME/dockerout participant

This is the equivalent of using ``--entrypoint=bash`` and omitting the qsipost
arguments in a ``docker`` command::

    $ docker run --rm -v $HOME/fullds005:/data:ro -v $HOME/dockerout:/out \
        -v $HOME/projects/qsipost/qsipost:/usr/local/miniconda/lib/python3.10/site-packages/qsipost:ro --entrypoint=bash \
        pennlinc/qsipost:latest

Patching containers can be achieved in Singularity analogous to ``docker``
using the ``--bind`` (``-B``) option: ::

    $ singularity run \
        -B $HOME/projects/qsipost/qsipost:/usr/local/miniconda/lib/python3.10/site-packages/qsipost \
        qsipost.img \
        /scratch/dataset /scratch/out participant -w /out/work/

Or you can patch Singularity containers using the PYTHONPATH variable: ::

   $ PYTHONPATH="$HOME/projects/qsipost" singularity run qsipost.img \
        /scratch/dataset /scratch/out participant -w /out/work/


Adding dependencies
===================
New dependencies to be inserted into the Docker image will either be
Python or non-Python dependencies.
Python dependencies may be added in three places, depending on whether
the package is large or non-release versions are required.
The image `must be rebuilt <#rebuilding-docker-image>`_ after any
dependency changes.

Python dependencies should generally be included in the ``REQUIRES``
list in `qsipost/info.py
<https://github.com/pennlinc/qsipost/blob/29133e5e9f92aae4b23dd897f9733885a60be311/qsipost/info.py#L46-L61>`_.
If the latest version in `PyPI <https://pypi.org/>`_ is sufficient,
then no further action is required.

For large Python dependencies where there will be a benefit to
pre-compiled binaries, `conda <https://github.com/conda/conda>`_ packages
may also be added to the ``conda install`` line in the `Dockerfile
<https://github.com/pennlinc/qsipost/blob/29133e5e9f92aae4b23dd897f9733885a60be311/Dockerfile#L46>`_.

Non-Python dependencies must also be installed in the Dockerfile, via a
``RUN`` command.
For example, installing an ``apt`` package may be done as follows: ::

    RUN apt-get update && \
        apt-get install -y <PACKAGE>

Rebuilding Docker image
=======================
If it is necessary to rebuild the Docker image, a local image named
``qsipost`` may be built from within the working qsipost
repository, located in ``~/projects/qsipost``: ::

    ~/projects/qsipost$ docker build -t qsipost .

To work in this image, replace ``pennlinc/qsipost:latest`` with
``qsipost`` in any of the above commands.
This image may be accessed by the ``qsipost-docker`` wrapper via the
``-i`` flag, e.g. ::

    $ qsipost-docker -i qsipost --shell


Adding new features to the citation boilerplate
===============================================

The citation boilerplate is built by adding two dunder attributes
of workflow objects: ``__desc__`` and ``__postdesc__``.
Once the full *qsipost* workflow is built, starting from the
outer workflow and visiting all sub-workflows in topological
order, all defined ``__desc__`` are appended to the citation
boilerplate before descending into sub-workflows.
Once all the sub-workflows of a given workflow have
been visited, then the ``__postdesc__`` attribute is appended
and the execution pops out to higher level workflows.
The dunder attributes are written in Markdown language, and may contain
references.
To add a reference, just add a new Bibtex entry to the references
database (``/qsipost/data/boilerplate.bib``).
You can then use the Bibtex handle within the Markdown text.
For example, if the Bibtex handle is ``myreference``, a citation
will be generated in Markdown language with ``@myreference``.
To generate citations with parenthesis and/or additional content,
brackets should be used: e.g. ``[see @myreference]`` will produce
a citation like *(see Doe J. et al 2018)*.


An example of how this works is shown here::

    workflow = Workflow(name=name)
    workflow.__desc__ = """\
    Head-motion parameters with respect to the DWI reference
    (transformation matrices, and six corresponding rotation and translation
    parameters) are estimated before any spatiotemporal filtering using
    `mcflirt` [FSL {fsl_ver}, @mcflirt].
    """.format(fsl_ver=fsl.Info().version() or '<ver>')
