.. include:: links.rst

Usage
-----

The ``qsipost`` preprocessing workflow takes as principal input the path of
the dataset that is to be processed. The input dataset is required to be in
valid :abbr:`BIDS (Brain Imaging Data Structure)` formate at least one
diffusion MRI series. The T1w image and the DWI may be in separate BIDS
<session> folders for a given subject. We highly recommend that you validate
your dataset with the free, online `BIDS Validator
<http://bids-standard.github.io/bids-validator/>`_.

The exact command to run ``qsipost`` depends on the Installation_ method.
The common parts of the command are similar to the `BIDS-Apps
<https://github.com/BIDS-Apps>`_ definition.
Example: ::

    qsipost data/bids_root/ out/ participant -w work/


Command-Line Arguments
======================

.. argparse::
   :ref: qsipost.cli.run.get_parser
   :prog: qsipost
   :nodefault:
   :nodefaultconst:


The docker wrapper CLI
======================

.. argparse::
   :ref: qsipost_docker.get_parser
   :prog: qsipost-docker
   :nodefault:
   :nodefaultconst:


The singularity wrapper CLI
=============================

.. argparse::
   :ref: qsipost_singularity.get_parser
   :prog: qsipost-docker
   :nodefault:
   :nodefaultconst:

Note on using CUDA
==================

The CUDA runtime version 9.1 is included in the QSIPost docker image.
The CUDA version of eddy is dramatically faster than the openmp version.
Information on running Docker with CUDA enabled can be found on
`dockerhub <https://github.com/NVIDIA/nvidia-docker/wiki/CUDA>`_. If running with singularity,
the call to singularity should include ``--nv``. To enable CUDA, see :ref:`configure_eddy`.

Debugging
=========

Logs and crashfiles are outputted into the
``<output dir>/qsipost/sub-<participant_label>/log`` directory.
Information on how to customize and understand these files can be found on the
`nipype debugging <http://nipype.readthedocs.io/en/latest/users/debug.html>`_
page.

CUDA Support
============

As of version 0.6.7 CUDA version 9.1 is supported in the QSIPost container! To run locally
using docker you will need the nvidia container runtime installed for Docker version 19.0.3
or higher. Singularity images will run with CUDA 9.1 with the ``-nv`` flag.


Support and communication
=========================

The documentation of this project is found here: http://qsipost.readthedocs.org/en/latest/.

All bugs, concerns and enhancement requests for this software can be submitted here:
https://github.com/pennlinc/qsipost/issues.
